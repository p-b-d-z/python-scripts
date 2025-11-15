# Agent Guidelines for Twilio IVR Project

## Commands
- **Run app**: `python3 call_handler.py` or `docker-compose up`
- **Build**: `docker build -t ivr:local .`
- **Install deps**: `pip install -r requirements.txt`
- **No tests configured**: Add pytest/unittest if needed
- **No linting configured**: Consider adding flake8/black

## Code Style
- **Imports**: stdlib first, then third-party (flask, twilio, requests, redis)
- **Naming**: snake_case for functions/variables, PascalCase for classes
- **Formatting**: 4 spaces, single quotes, 79 char line limit
- **Types**: No type hints currently used
- **Error handling**: Use try/except for API calls, validate inputs
- **Docstrings**: Add for public functions, follow Google style
- **Constants**: Define API keys/URLs as environment variables
- **Security**: Never commit credentials, use .env files

## Project Structure
- **call_handler.py**: Flask routes and Twilio integration only
- **call_helper.py**: Utility functions (phone validation, opt-out, agent management)
- **cache.py**: Redis/Valkey caching layer
- **templates/**: HTML template files for web interface
- **data/**: Persistent data storage (opt-out lists, recordings, cache)

## Key Endpoints
- **/**: SMS consent and opt-in page
- **/auth/agent**: Agent login/logout interface
- **/status/agents**: Real-time agent status dashboard
- **/incoming/sms**: SMS webhook handler
- **/incoming/voice**: Voice call webhook handler
- **/recording/save**: Call recording handler