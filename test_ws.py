"""Quick test of websockets 15.x process_request API"""
import asyncio
from websockets.asyncio.server import serve

async def ws_handler(websocket):
    await websocket.send('{"type":"connected"}')

async def process_request(connection, request):
    print(f"[HTTP] {request.method} {request.path}")
    if request.path == "/api/health":
        await connection.respond(200, '{"ok":true}', {"Content-Type": "application/json"})
    elif request.path == "/":
        await connection.respond(200, "<h1>OK</h1>", {"Content-Type": "text/html"})
    else:
        return None  # WS upgrade

async def main():
    print("Test server on :18765")
    async with serve(ws_handler, "127.0.0.1", 18765, process_request=process_request) as s:
        await s.serve_forever()

if __name__ == "__main__":
    asyncio.run(main())
