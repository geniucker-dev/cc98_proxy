if __name__ == "__main__":
    import uvicorn
    import os
    import sys
    import secrets
    import logging

    logging.basicConfig(level=logging.INFO)

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

    # randomize secret key
    os.environ["SECRET_KEY"] = secrets.token_urlsafe(32)

    uvicorn.run(
        "app:app",
        host=host,
        port=port,
        workers=workers,
        access_log=False
    )
