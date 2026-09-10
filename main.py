import os
from contextlib import asynccontextmanager
from dotenv import load_dotenv
import requests
from fastapi import FastAPI, Request

load_dotenv()

SYNERGIA_URL = "https://synergia.librus.pl"
LUCKY_NUMBER_URL = f"{SYNERGIA_URL}/gateway/api/2.0/LuckyNumbers"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:10.0) Gecko/20100101 Firefox/10.0",
    "Content-Type": "application/x-www-form-urlencoded",
}


def login(login: str, password: str) -> requests.Session:
    s = requests.Session()
    s.headers.update(HEADERS)
    s.headers["Referer"] = "https://portal.librus.pl/"

    r = s.get(f"{SYNERGIA_URL}/loguj/portalRodzina", allow_redirects=True)
    r = s.post(
        r.url,
        data={"action": "login", "login": login, "pass": password},
    )
    r = s.get(f"https://api.librus.pl{r.json()['goTo']}", allow_redirects=True)

    return s


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.session = login(os.getenv("LOGIN"), os.getenv("PASSWORD"))
    yield

app = FastAPI(lifespan=lifespan)


@app.get("/lucky-number")
def lucky_number(request: Request):
    s: requests.Session = request.app.state.session
    resp = s.get(LUCKY_NUMBER_URL)
    data = resp.json()
    return {"lucky_number": data["LuckyNumber"]["LuckyNumber"]}
