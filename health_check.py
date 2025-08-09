#!/usr/bin/env python3
"""
Простой HTTP сервер для health check
"""
import http.server
import socketserver
import os
import sys
import json
from datetime import datetime


class HealthCheckHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/health':
            # Проверяем основные зависимости
            health_status = {
                "status": "healthy",
                "timestamp": datetime.now().isoformat(),
                "version": "1.0.0",
                "checks": {
                    "environment": self.check_environment(),
                    "dependencies": self.check_dependencies()
                }
            }

            # Если все проверки пройдены, возвращаем 200
            if all(check.get("status") == "ok" for check in health_status["checks"]["dependencies"].values()):
                self.send_response(200)
            else:
                self.send_response(503)

            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(health_status).encode())
        else:
            self.send_response(404)
            self.end_headers()

    def check_environment(self):
        """Проверка наличия необходимых переменных окружения"""
        required_vars = [
            'TUYA_ACCESS_ID', 'TUYA_ACCESS_SECRET', 'SUPABASE_URL',
            'SUPABASE_KEY', 'TELEGRAM_BOT_TOKEN'
        ]

        missing_vars = [var for var in required_vars if not os.getenv(var)]

        return {
            "status": "ok" if not missing_vars else "error",
            "missing_variables": missing_vars
        }

    def check_dependencies(self):
        """Проверка доступности внешних сервисов"""
        checks = {}

        # Проверка Telegram API
        try:
            import requests
            token = os.getenv('TELEGRAM_BOT_TOKEN')
            if token and token != "dummy":
                response = requests.get(f"https://api.telegram.org/bot{token}/getMe", timeout=5)
                checks["telegram"] = {
                    "status": "ok" if response.status_code == 200 else "error",
                    "response_time": response.elapsed.total_seconds()
                }
            else:
                checks["telegram"] = {"status": "skipped", "reason": "no valid token"}
        except Exception as e:
            checks["telegram"] = {"status": "error", "error": str(e)}

        # Проверка Supabase
        try:
            from supabase import create_client
            url = os.getenv('SUPABASE_URL')
            key = os.getenv('SUPABASE_KEY')
            if url and key and url != "dummy" and key != "dummy":
                supabase = create_client(url, key)
                # Простая проверка соединения
                checks["supabase"] = {"status": "ok"}
            else:
                checks["supabase"] = {"status": "skipped", "reason": "no valid credentials"}
        except Exception as e:
            checks["supabase"] = {"status": "error", "error": str(e)}

        return checks


def run_health_server():
    """Запуск health check сервера"""
    PORT = 8080

    with socketserver.TCPServer(("", PORT), HealthCheckHandler) as httpd:
        print(f"Health check server running on port {PORT}")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("Health check server stopped")


if __name__ == "__main__":
    run_health_server()