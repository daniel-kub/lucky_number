import os
from datetime import datetime, timedelta
from contextlib import asynccontextmanager

import redis
import requests
from dotenv import load_dotenv
from fastapi import FastAPI, Request, HTTPException, Depends

load_dotenv()

SYNERGIA_URL = "https://synergia.librus.pl"
LUCKY_NUMBER_URL = f"{SYNERGIA_URL}/gateway/api/2.0/LuckyNumbers"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:10.0) Gecko/20100101 Firefox/10.0",
    "Content-Type": "application/x-www-form-urlencoded",
}

REDIS_KEY_PREFIX = "lucky_number:"
CACHE_HOUR = 6

REFRESH_KEY = os.getenv("REFRESH_KEY")


def verify_refresh_key(key: str | None = None) -> None:
    if not REFRESH_KEY:
        raise HTTPException(status_code=500, detail="REFRESH_KEY is not configured on the server")
    if key != REFRESH_KEY:
        raise HTTPException(status_code=403, detail="Invalid or missing refresh key")


def seconds_until_6am() -> int:
    now = datetime.now()
    target = now.replace(hour=CACHE_HOUR, minute=0, second=0, microsecond=0)
    if now >= target:
        target += timedelta(days=1)
    return int((target - now).total_seconds())


def login(login: str, password: str) -> requests.Session:
    print(f"[login] START - logowanie jako {login!r}")
    s = requests.Session()
    s.headers.update(HEADERS)
    s.headers["Referer"] = "https://portal.librus.pl/"

    r = s.get(f"{SYNERGIA_URL}/loguj/portalRodzina", allow_redirects=True)
    print(f"[login] Krok 1 (GET portalRodzina) - status={r.status_code}, url_koncowy={r.url}")

    r = s.post(
        r.url,
        data={"action": "login", "login": login, "pass": password},
    )
    print(f"[login] Krok 2 (POST login) - status={r.status_code}, body={r.text[:300]!r}")

    try:
        go_to = r.json()["goTo"]
    except (KeyError, ValueError) as e:
        print(f"[login] BŁĄD - brak 'goTo' w odpowiedzi po zalogowaniu: {e} | body={r.text[:500]!r}")
        raise

    r = s.get(f"https://api.librus.pl{go_to}", allow_redirects=True)
    print(f"[login] Krok 3 (GET {go_to}) - status={r.status_code}")
    print(f"[login] SUKCES - sesja utworzona, cookies={list(s.cookies.keys())}")

    return s


def fetch_lucky_number(session: requests.Session) -> int:
    print(f"[fetch_lucky_number] START - GET {LUCKY_NUMBER_URL}")
    resp = session.get(LUCKY_NUMBER_URL)
    print(f"[fetch_lucky_number] Status odpowiedzi: {resp.status_code}")

    try:
        data = resp.json()
    except ValueError as e:
        print(f"[fetch_lucky_number] BŁĄD parsowania JSON: {e} | raw body: {resp.text[:500]!r}")
        raise

    print(f"[fetch_lucky_number] Odebrane dane: {data}")

    try:
        number = data["LuckyNumber"]["LuckyNumber"]
    except (KeyError, TypeError) as e:
        print(f"[fetch_lucky_number] BŁĄD wyciągania klucza LuckyNumber: {e} | pełne data: {data}")
        raise

    print(f"[fetch_lucky_number] SUKCES - lucky_number={number}")
    return number


def today_key() -> str:
    return f"{REDIS_KEY_PREFIX}{datetime.now().strftime('%Y-%m-%d')}"


def get_cached_number(r: redis.Redis) -> int | None:
    val = r.get(today_key())
    return int(val) if val is not None else None


def set_cached_number(r: redis.Redis, number: int) -> None:
    ttl = seconds_until_6am()
    r.set(today_key(), number, ex=ttl)


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.session = login(os.getenv("LOGIN"), os.getenv("PASSWORD"))
    app.state.redis = redis.Redis(
        host=os.getenv("REDIS_HOST", "localhost"),
        port=int(os.getenv("REDIS_PORT", 6379)),
        db=int(os.getenv("REDIS_DB", 0)),
        decode_responses=True,
    )
    try:
        app.state.redis.ping()
    except redis.ConnectionError:
        raise RuntimeError("Cannot connect to Redis")
    yield
    app.state.redis.close()


app = FastAPI(lifespan=lifespan)


@app.get("/lucky-number")
def lucky_number(request: Request):
    print("[GET /lucky-number] Request przyjęty")
    r: redis.Redis = request.app.state.redis
    s: requests.Session = request.app.state.session

    cached = get_cached_number(r)
    if cached is not None:
        print(f"[GET /lucky-number] Trafienie w cache: {cached}")
        return {"lucky_number": cached, "source": "cache"}

    print("[GET /lucky-number] Brak w cache - pobieram z API Librusa")
    try:
        number = fetch_lucky_number(s)
    except Exception as e:
        print(f"[GET /lucky-number] BŁĄD podczas fetch_lucky_number: {type(e).__name__}: {e}")
        raise
    set_cached_number(r, number)
    print(f"[GET /lucky-number] SUKCES - number={number}, zapisano do cache")
    return {"lucky_number": number, "source": "api"}


@app.get("/lucky-number/refresh")
def lucky_number_refresh(request: Request, _: None = Depends(verify_refresh_key)):
    print("[GET /lucky-number/refresh] Ręczny refresh - loguję się ponownie")
    try:
        request.app.state.session = login(os.getenv("LOGIN"), os.getenv("PASSWORD"))
    except Exception as e:
        print(f"[GET /lucky-number/refresh] BŁĄD podczas login(): {type(e).__name__}: {e}")
        raise
    s: requests.Session = request.app.state.session
    r: redis.Redis = request.app.state.redis

    try:
        number = fetch_lucky_number(s)
    except Exception as e:
        print(f"[GET /lucky-number/refresh] BŁĄD podczas fetch_lucky_number: {type(e).__name__}: {e}")
        raise
    set_cached_number(r, number)
    print(f"[GET /lucky-number/refresh] SUKCES - number={number}")
    return {"lucky_number": number, "source": "refresh"}


@app.get("/health")
def health(request: Request):
    r: redis.Redis = request.app.state.redis
    try:
        r.ping()
        return {"status": "ok", "redis": "connected"}
    except redis.ConnectionError:
        return {"status": "error", "redis": "disconnected"}