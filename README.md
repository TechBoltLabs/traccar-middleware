# Traccar Middleware

A middleware application that receives location updates from Traccar and forwards them to both MQTT broker and HTTP endpoints.

## Docker Setup

This project includes Docker support for easy deployment.

### Prerequisites

- Docker
- Docker Compose

### Configuration

1. Create a `.env` file based on the `example.env` template:
   ```bash
   cp example.env .env
   ```

2. Edit the `.env` file to set your configuration values:
   ```
   # Required settings
   T2M_AUTH_SECRET=your_secret_auth_key_here
   MQTT_BROKER=your_mqtt_broker_address
   MQTT_USERNAME=your_mqtt_username
   MQTT_PASSWORD=your_mqtt_password

   # Optional settings with defaults
   T2M_PORT=7777
   T2M_LOG_FILENAME=logs/t2m.log
   T2M_LOG_LEVEL=INFO
   MQTT_PORT=1883
   MQTT_TOPIC=t2m/homeassistant/position
   MQTT_CLIENT_ID=traccar2mqtt-12345-python

   # HTTP endpoint configuration (optional)
   HTTP_ENDPOINT=http://your-api-endpoint/location
   HTTP_API_KEY=your_api_key
   HTTP_HEADERS='{"X-API-Key": "your_api_key", "User-Agent": "Traccar2MQTT/1.0"}'
   ```

### Building and Running

#### Using Docker Compose (recommended)

1. Build and start the container:
   ```bash
   docker-compose up -d
   ```

   The docker-compose.yml file uses the `env_file` option to load all environment variables from the .env file.

2. View logs:
   ```bash
   docker-compose logs -f
   ```

3. Stop the container:
   ```bash
   docker-compose down
   ```

#### Using Docker directly

1. Build the Docker image:
   ```bash
   docker build -t traccar-middleware .
   ```

2. Run the container with environment variables from the .env file:
   ```bash
   docker run -d \
     --name traccar-middleware \
     -p 7777:7777 \
     -v $(pwd)/logs:/app/logs \
     --env-file .env \
     --restart unless-stopped \
     traccar-middleware
   ```

## Usage

Once the container is running, the middleware will listen for position updates on port 7777.

Example request to send position data:
```
http://your-server:7777/positions?auth_secret=your_secret_auth_key_here&id=device1&lat=51.5074&lon=-0.1278
```

The middleware will forward this data to the configured MQTT broker and HTTP endpoint.
