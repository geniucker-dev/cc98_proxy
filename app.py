import httpx
import re
from fastapi import FastAPI, Request, Response, status
import jwt
from fastapi.responses import HTMLResponse, RedirectResponse
from urllib.parse import urljoin, urlparse
from functools import partial
from datetime import datetime, timedelta, timezone
import os
import logging
from io import StringIO
import csv


logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
logger.addHandler(logging.StreamHandler())
logger.addHandler(logging.FileHandler("log.csv", mode="a"))
app = FastAPI()

TO_PROXY = {
    "https://openid.cc98.org": "openid",
    "https://api.cc98.org": "api",
    "https://file.cc98.org": "file",
    "https://gaming.cc98.org": "gaming",
    "https://card.cc98.org": "card",
}

# JWT config
# random key
SECRET_KEY = os.environ["SECRET_KEY"]
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30  # token expiring time

def create_access_token(data: dict, expires_delta: timedelta):
    """
    generate JWT token
    """

    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + expires_delta
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

async def handler(base_url: str, request: Request, path: str):
    """
    handler for proxying request and rewriting response
    """

    url = urljoin(base_url, path)

    income_base_url = request.headers.get("x-forwarded-proto", "http") + "://" + request.headers.get("x-forwarded-host", request.url.netloc)

    headers = dict(request.headers)
    headers.pop("host", None)
    headers.pop("Host", None)
    if "cookie" in headers:
        cookies = headers["cookie"].split("; ")
        filtered_cookies = [c for c in cookies if not c.startswith("proxy_access_token=")]
        headers["cookie"] = "; ".join(filtered_cookies) if filtered_cookies else ""

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
            resp_content = re.sub(f"https?://{urlparse(url).netloc}".encode(), urljoin(income_base_url, f"{TO_PROXY[url]}" if TO_PROXY[url].startswith("http") else f"/proxy/{TO_PROXY[url]}").encode(), resp_content)
            if "Location" in resp.headers:
                resp.headers["Location"] = re.sub(f"https?://{urlparse(url).netloc}".encode(), urljoin(income_base_url, f"{TO_PROXY[url]}" if TO_PROXY[url].startswith("http") else f"/proxy/{TO_PROXY[url]}").encode(), resp.headers["Location"].encode()).decode()
        resp_content = re.sub(b"https?://www.cc98.org", income_base_url.encode(), resp_content)
        if "Location" in resp.headers:
            resp.headers["Location"] = re.sub(b"https?://www.cc98.org", income_base_url.encode(), resp.headers["Location"].encode()).decode()

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


async def get_current_user(request: Request):
    """
    get current user from cookie
    """

    token = request.cookies.get("proxy_access_token")
    if not token:
        return None
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            return None
        return username
    except jwt.PyJWTError:
        return None

@app.middleware("http")
async def check_auth(request: Request, call_next):
    """
    middleware for checking authentication
    """

    # skip login page
    if request.url.path == "/login" or request.url.path == "/robots.txt":
        return await call_next(request)
    # check token
    current_user = await get_current_user(request)
    if current_user is None:
        # if not authenticated, redirect to login page
        next_url = request.url.path
        if request.query_params:
            next_url += "?" + str(request.query_params)
        return RedirectResponse(url=f"/login?next={next_url}")
    return await call_next(request)

@app.middleware("http")
async def log_request(request: Request, call_next):
    """
    middleware for logging request
    """

    client_host = request.headers.get("x-forwarded-for", request.client.host)
    user_agent = request.headers.get("user-agent", "-")
    request_line = f"{request.method} {request.url.path}"
    if request.url.query:
        request_line += f"?{request.url.query}"
    request_line += f' HTTP/{request.scope.get("http_version", "1.1")}'

    try:
        response = await call_next(request)
        log_message_io = StringIO()
        csv_writer = csv.writer(log_message_io, lineterminator="")
        csv_writer.writerow([datetime.now().astimezone().isoformat(), client_host, request_line, response.status_code, user_agent])
        logger.info(log_message_io.getvalue())
        return response
    except:
        log_message_io = StringIO()
        csv_writer = csv.writer(log_message_io, lineterminator="")
        csv_writer.writerow([datetime.now().astimezone().isoformat(), client_host, request_line, 500, user_agent])
        logger.error(log_message_io.getvalue())
        raise

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, next: str = "/"):
    """
    login page
    """

    html_content = f"""
    <!DOCTYPE html>
    <html lang="zh-CN">
    <head>
        <meta charset="UTF-8">
        <title>登录</title>
    </head>
    <body>
        <h1>登录</h1>
        <form method="post" action="/login?next={next}">
            <label for="username">用户名:</label>
            <input type="text" id="username" name="username"><br>
            <label for="password">密码:</label>
            <input type="password" id="password" name="password"><br>
            <input type="submit" value="登录">
        </form>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)

@app.post("/login")
async def login_submit(request: Request, next: str = "/"):
    """
    login submit
    """

    form = await request.form()
    username = form.get("username")
    password = form.get("password")

    # use openid to check if username and password are correct
    transport = httpx.AsyncHTTPTransport(retries=3)
    async with httpx.AsyncClient(transport=transport) as client:
        resp = await client.post(
            "https://openid.cc98.org/connect/token",
            data={
                "client_id": "9a1fd200-8687-44b1-4c20-08d50a96e5cd",
                "client_secret": "8b53f727-08e2-4509-8857-e34bf92b27f2",
                "grant_type": "password",
                "username": username,
                "password": password,
            },
        )

    if resp.status_code == 200 and "access_token" in resp.json():
        access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
        access_token = create_access_token(
            data={"sub": username}, expires_delta=access_token_expires
        )
        response = RedirectResponse(url=next, status_code=status.HTTP_303_SEE_OTHER)
        response.set_cookie(key="proxy_access_token", value=access_token, httponly=True)
        return response
    else:
        html_content = f"""
        <!DOCTYPE html>
        <html lang="zh-CN">
        <head>
            <meta charset="UTF-8">
            <title>登录</title>
        </head>
        <body>
            <h1>登录</h1>
            <p style="color: red;">用户名或密码错误</p>
            <form method="post" action="/login?next={next}">
                <label for="username">用户名:</label>
                <input type="text" id="username" name="username"><br>
                <label for="password">密码:</label>
                <input type="password" id="password" name="password"><br>
                <input type="submit" value="登录">
            </form>
        </body>
        </html>
        """
        return HTMLResponse(content=html_content)

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

