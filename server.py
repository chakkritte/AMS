#!/usr/bin/env python3
import os
import json
import urllib.request
import urllib.parse
import urllib.error
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
import mimetypes

PORT = 8080
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
AGENTS_DIR = os.path.join(BASE_DIR, 'agents')

# Ensure agents directory exists
if not os.path.exists(AGENTS_DIR):
    os.makedirs(AGENTS_DIR)

def is_safe_id(agent_id):
    return all(c.isalnum() or c in '-_' for c in agent_id) and len(agent_id) > 0

class AgentOfficeRequestHandler(BaseHTTPRequestHandler):
    def end_headers(self):
        # Add CORS headers
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, PUT, DELETE, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(204)
        self.end_headers()

    def do_GET(self):
        # Parse query params
        parsed_url = urllib.parse.urlparse(self.path)
        path = parsed_url.path
        
        if path == '/agents/export':
            self.export_agents()
        elif path == '/agents' or path == '/agents/':
            self.list_agents()
        elif path.startswith('/agents/'):
            agent_id = path[len('/agents/'):]
            self.get_agent(agent_id)
        elif path == '/ollama/models':
            # Extract 'url' query param if provided
            query = urllib.parse.parse_qs(parsed_url.query)
            ollama_base = query.get('url', ['http://localhost:11434'])[0]
            self.get_ollama_models(ollama_base)
        elif path == '/' or path == '/index.html':
            self.serve_static_file('index.html')
        else:
            # Serve other static files
            filename = path.lstrip('/')
            # Prevent directory traversal
            safe_path = os.path.abspath(os.path.join(BASE_DIR, filename))
            if safe_path.startswith(BASE_DIR) and os.path.exists(safe_path) and os.path.isfile(safe_path):
                self.serve_static_file(filename)
            else:
                self.send_error(404, "File not found")

    def do_POST(self):
        path = self.path.split('?')[0]
        if path == '/agents' or path == '/agents/':
            self.save_agent(is_new=True)
        else:
            self.send_error(404, "Endpoint not found")

    def do_PUT(self):
        path = self.path.split('?')[0]
        if path.startswith('/agents/'):
            agent_id = path[len('/agents/'):]
            self.save_agent(is_new=False, agent_id=agent_id)
        else:
            self.send_error(404, "Endpoint not found")

    def do_DELETE(self):
        path = self.path.split('?')[0]
        if path.startswith('/agents/'):
            agent_id = path[len('/agents/'):]
            self.delete_agent(agent_id)
        else:
            self.send_error(404, "Endpoint not found")

    def serve_static_file(self, filename):
        filepath = os.path.join(BASE_DIR, filename)
        try:
            with open(filepath, 'rb') as f:
                content = f.read()
            self.send_response(200)
            mime_type, _ = mimetypes.guess_type(filepath)
            if mime_type:
                self.send_header('Content-Type', mime_type)
            else:
                self.send_header('Content-Type', 'application/octet-stream')
            self.end_headers()
            self.wfile.write(content)
        except IOError:
            self.send_error(404, f"File {filename} not found")

    def export_agents(self):
        import zipfile
        import io
        try:
            # Create zip in memory
            memory_file = io.BytesIO()
            with zipfile.ZipFile(memory_file, 'w', zipfile.ZIP_DEFLATED) as zip_file:
                for file_name in os.listdir(AGENTS_DIR):
                    if file_name.endswith('.json'):
                        file_path = os.path.join(AGENTS_DIR, file_name)
                        zip_file.write(file_path, file_name)
            
            memory_file.seek(0)
            self.send_response(200)
            self.send_header('Content-Type', 'application/zip')
            self.send_header('Content-Disposition', 'attachment; filename=agents_backup.zip')
            self.end_headers()
            self.wfile.write(memory_file.read())
        except Exception as e:
            self.send_error(500, f"Error exporting agents: {e}")

    def list_agents(self):
        agents = []
        try:
            for file_name in os.listdir(AGENTS_DIR):
                if file_name.endswith('.json'):
                    file_path = os.path.join(AGENTS_DIR, file_name)
                    try:
                        with open(file_path, 'r', encoding='utf-8') as f:
                            agent_data = json.load(f)
                            agents.append(agent_data)
                    except Exception as e:
                        print(f"Error reading file {file_name}: {e}", file=sys.stderr)
            
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(agents).encode('utf-8'))
        except Exception as e:
            self.send_error(500, f"Error listing agents: {e}")

    def get_agent(self, agent_id):
        if not is_safe_id(agent_id):
            self.send_error(400, "Invalid Agent ID format")
            return
        
        file_path = os.path.join(AGENTS_DIR, f"{agent_id}.json")
        if not os.path.exists(file_path):
            self.send_error(404, "Agent not found")
            return

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                agent_data = f.read()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(agent_data.encode('utf-8'))
        except Exception as e:
            self.send_error(500, f"Error loading agent: {e}")

    def save_agent(self, is_new, agent_id=None):
        try:
            content_length = int(self.headers.get('Content-Length', 0))
            if content_length == 0:
                self.send_error(400, "Empty request body")
                return

            body = self.rfile.read(content_length)
            agent_data = json.loads(body.decode('utf-8'))

            if is_new:
                # Expect ID or generate one if not present
                if 'id' not in agent_data or not agent_data['id']:
                    # Frontend will supply ID, but as fallback:
                    import uuid
                    agent_data['id'] = str(uuid.uuid4())
                agent_id = agent_data['id']
            else:
                if not agent_id:
                    agent_id = agent_data.get('id')
                if not agent_id:
                    self.send_error(400, "Agent ID missing")
                    return

            if not is_safe_id(agent_id):
                self.send_error(400, "Invalid Agent ID format")
                return

            file_path = os.path.join(AGENTS_DIR, f"{agent_id}.json")
            
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(agent_data, f, indent=2, ensure_ascii=False)

            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(agent_data).encode('utf-8'))
        except Exception as e:
            self.send_error(500, f"Error saving agent: {e}")

    def delete_agent(self, agent_id):
        if not is_safe_id(agent_id):
            self.send_error(400, "Invalid Agent ID format")
            return

        file_path = os.path.join(AGENTS_DIR, f"{agent_id}.json")
        if not os.path.exists(file_path):
            self.send_error(404, "Agent not found")
            return

        try:
            os.remove(file_path)
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({"success": True, "id": agent_id}).encode('utf-8'))
        except Exception as e:
            self.send_error(500, f"Error deleting agent: {e}")

    def get_ollama_models(self, ollama_base):
        ollama_base = ollama_base.rstrip('/')
        tags_url = f"{ollama_base}/api/tags"
        
        try:
            req = urllib.request.Request(tags_url)
            with urllib.request.urlopen(req, timeout=3) as response:
                data = response.read()
                
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(data)
        except Exception as e:
            # Fallback models in case Ollama is not running or accessible
            fallback_data = {
                "models": [
                    {"name": "llama3:8b", "details": {"parameter_size": "8B", "family": "llama"}},
                    {"name": "mistral:latest", "details": {"parameter_size": "7B", "family": "mistral"}},
                    {"name": "phi3:latest", "details": {"parameter_size": "3.8B", "family": "phi"}},
                    {"name": "gemma:7b", "details": {"parameter_size": "8B", "family": "gemma"}},
                    {"name": "codegemma:latest", "details": {"parameter_size": "7B", "family": "gemma"}},
                    {"name": "qwen2:7b", "details": {"parameter_size": "7B", "family": "qwen"}}
                ],
                "fallback": True,
                "error": str(e)
            }
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(fallback_data).encode('utf-8'))

def run(server_class=HTTPServer, handler_class=AgentOfficeRequestHandler, port=PORT):
    server_address = ('', port)
    httpd = server_class(server_address, handler_class)
    print(f"Pixel Agent Office server running on http://localhost:{port}...")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down server...")
        httpd.server_close()

if __name__ == '__main__':
    run()
