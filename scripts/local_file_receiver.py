
import json
import hmac
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


# Configuration
SAVE_DIRECTORY = Path(
    os.getenv("SAVE_DIRECTORY", str(Path.home() / "n8n"))
).expanduser().resolve()

HOST = os.getenv("FILE_RECEIVER_HOST", "0.0.0.0")
PORT = int(os.getenv("FILE_RECEIVER_PORT", "8000"))
AUTH_TOKEN = os.getenv("FILE_RECEIVER_TOKEN", "")

MAX_REQUEST_BYTES = int(
    os.getenv("MAX_REQUEST_BYTES", str(10 * 1024 * 1024))
)


class FileReceiverHandler(BaseHTTPRequestHandler):

    def send_json(self, status_code, data):
        response = json.dumps(data).encode("utf-8")

        self.send_response(status_code)
        self.send_header(
            "Content-Type", "application/json; charset=utf-8"
        )
        self.send_header("Content-Length", str(len(response)))
        self.end_headers()
        self.wfile.write(response)

    def do_POST(self):

        # Require a bearer token supplied by the n8n HTTP Request node.
        supplied_token = self.headers.get("Authorization", "")
        expected_token = f"Bearer {AUTH_TOKEN}"

        if not hmac.compare_digest(supplied_token, expected_token):
            self.send_json(401, {
                "status": "error",
                "message": "Unauthorized request."
            })
            return

        # Validate the request size.
        content_length = self.headers.get("Content-Length")

        if content_length is None:
            self.send_json(411, {
                "status": "error",
                "message": "Content-Length header required."
            })
            return

        try:
            content_length = int(content_length)
        except ValueError:
            self.send_json(400, {
                "status": "error",
                "message": "Invalid content length."
            })
            return

        if content_length <= 0:
            self.send_json(400, {
                "status": "error",
                "message": "Request body is empty."
            })
            return

        if content_length > MAX_REQUEST_BYTES:
            self.send_json(413, {
                "status": "error",
                "message": "Request exceeds the allowed size."
            })
            return

        try:
            post_data = self.rfile.read(content_length)

            if len(post_data) != content_length:
                self.send_json(400, {
                    "status": "error",
                    "message": "Incomplete request body."
                })
                return

            payload = json.loads(post_data.decode("utf-8"))

            if not isinstance(payload, dict):
                self.send_json(400, {
                    "status": "error",
                    "message": "Invalid JSON payload."
                })
                return

            filename = payload.get("filename", "untitled.md")
            file_content = payload.get("text", "")

            if not isinstance(filename, str) or not isinstance(file_content, str):
                self.send_json(400, {
                    "status": "error",
                    "message": "Filename and text must be strings."
                })
                return

            filename = filename.strip()

            # Prevent invalid filenames and directory traversal.
            invalid_characters = '<>:"/\\|?*'

            if (
                not filename
                or filename in {".", ".."}
                or len(filename) > 255
                or any(char in filename for char in invalid_characters)
                or any(ord(char) < 32 for char in filename)
                or filename.endswith((" ", "."))
            ):
                self.send_json(400, {
                    "status": "error",
                    "message": "Invalid filename."
                })
                return

            # Save the extracted text locally using UTF-8 encoding.
            SAVE_DIRECTORY.mkdir(parents=True, exist_ok=True)

            file_path = SAVE_DIRECTORY / filename

            file_path.write_text(
                file_content,
                encoding="utf-8"
            )

            print(f"Successfully saved: {filename}")

            self.send_json(200, {
                "status": "success",
                "filename": filename
            })

        except (json.JSONDecodeError, UnicodeDecodeError):
            self.send_json(400, {
                "status": "error",
                "message": "Invalid JSON or text encoding."
            })

        except OSError as error:
            print(f"File processing error: {error}")

            self.send_json(500, {
                "status": "error",
                "message": "Unable to save the file."
            })


def run():

    if len(AUTH_TOKEN) < 24:
        raise SystemExit(
            "Set FILE_RECEIVER_TOKEN to a secret of at least 24 characters."
        )

    SAVE_DIRECTORY.mkdir(parents=True, exist_ok=True)

    server = ThreadingHTTPServer(
        (HOST, PORT),
        FileReceiverHandler
    )

    print(f"File receiver listening on port {PORT}")
    print(f"Save directory: {SAVE_DIRECTORY}")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down file receiver.")
    finally:
        server.server_close()


if __name__ == "__main__":
    run()
