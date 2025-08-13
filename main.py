#!/usr/bin/env python3
"""
Traccar to MQTT/HTTP Middleware
Receives location updates from Traccar and forwards them to both MQTT broker and HTTP endpoints
"""

import json
import logging
import os
import random
import signal
import sys
from typing import Optional

import asyncio
import aiohttp
from aiohttp import web
from dotenv import load_dotenv
import paho.mqtt.client as mqtt


# Default constants
T2M_PORT_DEFAULT = 7777
LOG_FILENAME_DEFAULT = 'logs/t2m.log'
LOG_LEVEL_DEFAULT = 'DEBUG'
MQTT_PORT_DEFAULT = 1883
MQTT_TOPIC_DEFAULT = 't2m/homeassistant/position/'
MQTT_CLIENT_ID_DEFAULT_PREFIX = 'traccar2mqtt-'

# Global variables
auth_secret: str
port: int
log_filename: str
log_level: str
mqtt_broker: str
mqtt_port: int
mqtt_username: str
mqtt_password: str
mqtt_topic: str
mqtt_client_id: str
mqtt_client: mqtt.Client
http_endpoint: Optional[str]
http_headers: dict

# Logger setup
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)


def setup_logging():
    """Configure logging based on environment settings"""
    log_format = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'

    # Create logs directory if it doesn't exist
    os.makedirs(os.path.dirname(log_filename), exist_ok=True)

    logging.basicConfig(
        level=getattr(logging, log_level),
        format=log_format,
        handlers=[
            logging.FileHandler(log_filename),
            logging.StreamHandler(sys.stdout)
        ]
    )


def on_mqtt_connect(client, userdata, flags, rc):
    """MQTT connection callback"""
    if rc == 0:
        logger.info("Connected to MQTT broker")
    else:
        logger.error(f"Failed to connect to MQTT broker, return code {rc}")


def on_mqtt_disconnect(client, userdata, rc):
    """MQTT disconnection callback"""
    logger.info("Disconnected from MQTT broker")


def initialize_mqtt_client():
    """Initialize and connect to MQTT broker"""
    global mqtt_client

    # Use callback_api_version for compatibility with paho-mqtt 2.x
    mqtt_client = mqtt.Client(
        client_id=mqtt_client_id,
        callback_api_version=mqtt.CallbackAPIVersion.VERSION1
    )
    mqtt_client.username_pw_set(mqtt_username, mqtt_password)
    mqtt_client.on_connect = on_mqtt_connect
    mqtt_client.on_disconnect = on_mqtt_disconnect

    try:
        mqtt_client.connect(mqtt_broker, mqtt_port, 60)
        mqtt_client.loop_start()
        logger.info(f"MQTT client initialized for broker {mqtt_broker}:{mqtt_port}")
    except Exception as e:
        logger.error(f"Could not connect to MQTT broker: {e}")
        sys.exit(1)


def build_mqtt_message_payload(client_id: str, latitude: str, longitude: str) -> str:
    """Build MQTT message payload"""
    payload = {
        "clientId": client_id,
        "latitude": latitude,
        "longitude": longitude
    }
    return json.dumps(payload)


async def send_mqtt_message(client_id: str, latitude: str, longitude: str):
    """Send location update via MQTT"""
    try:
        payload = build_mqtt_message_payload(client_id, latitude, longitude)
        if mqtt_topic.endswith('/'):
            unique_mqtt_topic = f"{mqtt_topic}{client_id}"
        else:
            unique_mqtt_topic = f"{mqtt_topic}/{client_id}"

        logger.info(f"Sending MQTT message: {payload} to topic: {unique_mqtt_topic}")

        result = mqtt_client.publish(unique_mqtt_topic, payload, qos=1)

        if result.rc == mqtt.MQTT_ERR_SUCCESS:
            logger.info(f"MQTT message sent successfully for client {client_id}")
        else:
            logger.error(f"Failed to send MQTT message, return code: {result.rc}")

    except Exception as e:
        logger.error(f"Error sending MQTT message: {e}")


async def send_http_post(client_id: str, latitude: str, longitude: str):
    """Send location update via HTTP POST"""
    if not http_endpoint:
        logger.debug("HTTP endpoint not configured, skipping HTTP POST")
        return

    try:
        # Build the API URL with object_id path parameter
        # http_endpoint should be like: https://api.example.com/api/v1/location
        api_url = f"{http_endpoint.rstrip('/')}/{client_id}"

        # API expects lat and lon fields as numbers
        payload = {
            "lat": float(latitude),
            "lon": float(longitude)
        }

        logger.info(f"Attempting HTTP POST to: {api_url}")
        logger.info(f"Headers: {http_headers}")
        logger.info(f"Payload: {payload}")

        async with aiohttp.ClientSession() as session:
            async with session.post(
                    api_url,
                    json=payload,
                    headers=http_headers,
                    timeout=aiohttp.ClientTimeout(total=10)
            ) as response:
                logger.info(f"HTTP response status: {response.status}")
                response_text = await response.text()
                logger.info(f"HTTP response body: {response_text}")

                if response.status == 200:
                    logger.info(f"HTTP POST sent successfully for client {client_id}")
                else:
                    logger.error(f"HTTP POST failed with status {response.status}: {await response.text()}")

    except asyncio.TimeoutError:
        logger.error(f"HTTP POST timeout for client {client_id}")
    except ValueError as e:
        logger.error(f"Invalid latitude/longitude values: {e}")
    except Exception as e:
        logger.error(f"Error sending HTTP POST: {e}")
        import traceback
        logger.error(f"Full traceback: {traceback.format_exc()}")


async def positions_handler(request):
    """Handle incoming position updates from Traccar"""
    try:
        # Check authorization
        request_auth_secret = request.query.get('auth_secret')
        if request_auth_secret != auth_secret:
            logger.warning("Unauthorized access attempt")
            return web.Response(status=403, text='Not authorized!\n')

        # Extract required parameters
        request_client_id = request.query.get('id')
        request_latitude = request.query.get('lat')
        request_longitude = request.query.get('lon')

        # Validate required parameters
        if not all([request_client_id, request_latitude, request_longitude]):
            error_msg = (
                'Error: One or more required parameters are not provided correctly.\n'
                'Required parameters: "id" (the unique identifier of the tracked object), '
                '"lat" (position latitude), "lon" (position longitude)\n'
            )
            logger.warning(f"Bad request: missing parameters")
            return web.Response(status=400, text=error_msg)

        logger.info(f"Received location update for client {request_client_id}: "
                    f"lat={request_latitude}, lon={request_longitude}")

        # Send to both MQTT and HTTP endpoints concurrently
        await asyncio.gather(
            send_mqtt_message(request_client_id, request_latitude, request_longitude),
            send_http_post(request_client_id, request_latitude, request_longitude),
            return_exceptions=True
        )

        return web.Response(status=200, text='')

    except Exception as e:
        logger.error(f"Error handling position update: {e}")
        return web.Response(status=500, text='Internal server error\n')


def initialize_project_settings():
    """Initialize project settings from environment variables"""
    global auth_secret, port, log_filename, log_level
    global mqtt_broker, mqtt_port, mqtt_username, mqtt_password, mqtt_topic, mqtt_client_id
    global http_endpoint, http_headers

    # Required environment variables
    auth_secret = os.getenv('T2M_AUTH_SECRET')
    if not auth_secret:
        print("Error: T2M_AUTH_SECRET environment variable is required")
        sys.exit(1)

    mqtt_broker = os.getenv('MQTT_BROKER')
    if not mqtt_broker:
        print("Error: MQTT_BROKER environment variable is required")
        sys.exit(1)

    mqtt_username = os.getenv('MQTT_USERNAME')
    if not mqtt_username:
        print("Error: MQTT_USERNAME environment variable is required")
        sys.exit(1)

    mqtt_password = os.getenv('MQTT_PASSWORD')
    if not mqtt_password:
        print("Error: MQTT_PASSWORD environment variable is required")
        sys.exit(1)

    # Optional environment variables with defaults
    port = int(os.getenv('T2M_PORT', T2M_PORT_DEFAULT))
    log_filename = os.getenv('T2M_LOG_FILENAME', LOG_FILENAME_DEFAULT)
    log_level = os.getenv('T2M_LOG_LEVEL', LOG_LEVEL_DEFAULT).upper()
    mqtt_port = int(os.getenv('MQTT_PORT', MQTT_PORT_DEFAULT))
    mqtt_topic = os.getenv('MQTT_TOPIC', MQTT_TOPIC_DEFAULT)
    mqtt_client_id = os.getenv(
        'MQTT_CLIENT_ID',
        f"{MQTT_CLIENT_ID_DEFAULT_PREFIX}{random.randint(10000, 99999)}"
    ).lower()

    # HTTP endpoint configuration (optional)
    http_endpoint = os.getenv('HTTP_ENDPOINT')

    # HTTP headers (optional, defaults to JSON content type)
    http_headers = {
        'Content-Type': 'application/json'
    }

    # API Key authentication for HTTP endpoint
    api_key = os.getenv('HTTP_API_KEY')
    if api_key:
        http_headers['X-API-Key'] = api_key

    # Allow custom HTTP headers via environment variables (for backward compatibility)
    auth_header = os.getenv('HTTP_AUTH_HEADER')
    if auth_header:
        http_headers['Authorization'] = auth_header

    # Parse additional headers from HTTP_HEADERS env var (JSON format)
    additional_headers = os.getenv('HTTP_HEADERS')
    if additional_headers:
        try:
            parsed_headers = json.loads(additional_headers)
            http_headers.update(parsed_headers)
        except json.JSONDecodeError:
            logger.warning("Invalid JSON format in HTTP_HEADERS environment variable")


def print_settings():
    """Print all configuration settings (excluding sensitive data)"""
    print(f"authSecret: {'*' * len(auth_secret)}")
    print(f"port: {port}")
    print(f"logFilename: {log_filename}")
    print(f"logLevel: {log_level}")
    print(f"mqttBroker: {mqtt_broker}")
    print(f"mqttPort: {mqtt_port}")
    print(f"mqttUsername: {mqtt_username}")
    print(f"mqttPassword: {'*' * len(mqtt_password)}")
    print(f"mqttTopic: {mqtt_topic}")
    print(f"mqttClientId: {mqtt_client_id}")
    print(f"httpEndpoint: {http_endpoint or 'Not configured'}")
    print(f"httpHeaders: {http_headers}")


async def cleanup():
    """Cleanup resources on shutdown"""
    logger.info("Shutting down...")

    if mqtt_client and mqtt_client.is_connected():
        mqtt_client.loop_stop()
        mqtt_client.disconnect()
        logger.info("Disconnected from MQTT broker")

    logger.info("Shutdown complete")


def signal_handler(signum, frame):
    """Handle shutdown signals"""
    logger.info(f"Received signal {signum}")
    asyncio.create_task(cleanup())


async def main():
    """Main application entry point"""
    # Load environment variables
    load_dotenv()

    # Check required environment variables
    required_vars = ['T2M_AUTH_SECRET', 'MQTT_BROKER', 'MQTT_USERNAME', 'MQTT_PASSWORD']
    missing_vars = [var for var in required_vars if not os.getenv(var)]

    if missing_vars:
        print(f"Error: Missing required environment variables: {', '.join(missing_vars)}")
        sys.exit(1)

    # Initialize project settings
    initialize_project_settings()

    # Setup logging
    setup_logging()

    # Print settings (for debugging)
    # print_settings()

    # Initialize MQTT connection
    initialize_mqtt_client()

    # Setup signal handlers for graceful shutdown
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Add middleware for request logging
    @web.middleware
    async def log_requests_middleware(request, handler):
        start_time = asyncio.get_event_loop().time()
        response = await handler(request)
        process_time = asyncio.get_event_loop().time() - start_time
        logger.info(f"{request.method} {request.path} {response.status} {process_time:.3f}s")
        return response

    # Create the web application
    app = web.Application(middlewares=[log_requests_middleware])
    app.router.add_get('/positions', positions_handler)

    # Start the web server
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()

    logger.info(f"Server listening on port {port}")
    print(f"Server listening on port {port}")

    # Keep the server running
    try:
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        logger.info("Received keyboard interrupt")
    finally:
        await cleanup()
        await runner.cleanup()


if __name__ == '__main__':
    asyncio.run(main())