import httpx
import re
from fastapi import FastAPI, Request, Response
from urllib.parse import urljoin, urlparse
from functools import partial

app = FastAPI()


TO_PROXY = {
    "https://openid.cc98.org": "openid",
    "https://api.cc98.org": "api",
    "https://file.cc98.org": "file",
    "https://gaming.cc98.org": "gaming",
    "https://card.cc98.org": "card",
}


async def handler(base_url: str, request: Request, path: str):
    """
    handler for proxying request and rewriting response
    """

    url = urljoin(base_url, path)

    headers = dict(request.headers)
    headers.pop("host", None)
    headers.pop("Host", None)

    transport = httpx.AsyncHTTPTransport(retries=3)
    async with httpx.AsyncClient(transport=transport) as client:
        resp = await client.request(
            method=request.method,
            url=url,
            headers=headers,
            data=await request.body(),
            params=dict(request.query_params),
        )

        resp_content = resp.content

        for url in TO_PROXY:
            # replace https?://domain with TO_PROXY[domain]
            resp_content = re.sub(f"https?://{urlparse(url).netloc}".encode(), urljoin(str(request.base_url), f"{TO_PROXY[url]}" if TO_PROXY[url].startswith("http") else f"/proxy/{TO_PROXY[url]}").encode(), resp_content)
            if "Location" in resp.headers:
                resp.headers["Location"] = re.sub(f"https?://{urlparse(url).netloc}".encode(), urljoin(str(request.base_url), f"{TO_PROXY[url]}" if TO_PROXY[url].startswith("http") else f"/proxy/{TO_PROXY[url]}").encode(), resp.headers["Location"].encode()).decode()

        # rewrite absolute path in href, src, action to {path}+absolute_path
        # but keep those already start with /proxy
        def replace_url_html(match: re.Match):
            url = match.group("url")
            if url.startswith(b"/") and not url.startswith(b"/proxy"):
                prefix = ""
                for u in TO_PROXY:
                    if request.url.path.startswith(f"/proxy/{TO_PROXY[u]}"):
                        prefix = f"/proxy/{TO_PROXY[u]}"
                        break
                return f'{match.group("attr").decode()}="{prefix}{url.decode()}"'.encode()
            else:
                return match.group(0)
        resp_content = re.sub(b'(?P<attr>href|src|action)="(?P<url>[^"]+)"', replace_url_html, resp_content)

        # rewrite url splicing
        if resp.headers.get("Content-Type", "").startswith("application/javascript"):
            # replace new URL(a, b) with b + a
            # re.sub(r"new URL\(([^,]+),\s*([^)]+)\)", r"\2 + \1", resp_text)
            resp_content = re.sub(b'new URL\\(([^,]+),\\s*([^\\)]+)\\)', b'\\2 + \\1', resp_content)

        # rewrite location header (absolute path)
        # keep those already start with /proxy
        if "Location" in resp.headers:
            location = resp.headers["Location"]
            if location.startswith("/") and not location.startswith("/proxy"):
                prefix = ""
                for url in TO_PROXY:
                    if request.url.path.startswith(f"/proxy/{TO_PROXY[url]}"):
                        prefix = f"/proxy/{TO_PROXY[url]}"
                        break
                resp.headers["Location"] = f"{prefix}{location}"

        # return Response(content=resp_text, status_code=resp.status_code, headers=dict(resp.headers))
        resp.headers.pop("Content-Length", None)
        resp.headers.pop("Content-Encoding", None)
        return Response(content=resp_content, status_code=resp.status_code, headers=dict(resp.headers))

# robots.txt: Disallow all
@app.get("/robots.txt")
async def robots():
    return Response(content="User-agent: *\nDisallow: /", media_type="text/plain")

# register proxy routes
for url in TO_PROXY:
    app.api_route(f"/proxy/{TO_PROXY[url]}{{path:path}}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"])(partial(handler, url))

# proxy other requests
@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"])
async def proxy(request: Request, path: str):
    return await handler("https://www.cc98.org", request, path)


if __name__ == "__main__":
    import uvicorn
    import os
    import sys

    host = os.getenv("HOST", "127.0.0.1")
    port = os.getenv("PORT", 8000)
    workers = os.getenv("WORKERS", 1)

    # check validation of host, port, workers
    try:
        port = int(port)
        if port < 1 or port > 65535:
            raise ValueError
    except ValueError:
        print("Invalid port number")
        sys.exit(1)
    try:
        workers = int(workers)
        if workers < 1:
            raise ValueError
    except ValueError:
        print("Invalid number of workers")
        sys.exit(1)

    uvicorn.run(app, host=host, port=port, workers=workers)
