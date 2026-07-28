@echo off
setlocal
set "LLMLOADER2_COMMAND_SERVICE_AUTH_ME_URL=http://localhost:8000/v1/auth/me"
set "LLMLOADER2_COMMAND_SERVICE_BIND=127.0.0.1"
set "LLMLOADER2_COMMAND_SERVICE_PORT=8777"
python -m command_services.command_service
endlocal
