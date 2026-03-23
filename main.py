import os
from contextlib import asynccontextmanager
from dotenv import load_dotenv
from librus_apix.client import Client, Token, new_client
from librus_apix.student_information import get_student_information
from fastapi import FastAPI, Request

load_dotenv()

@asynccontextmanager
async def lifespan(app: FastAPI):
    client: Client = new_client()
    _token: Token = client.get_token(os.getenv("LOGIN"), os.getenv("PASSWORD"))
    app.state.client = client
    
    yield
    
    # tutaj możesz dodać cleanup jeśli biblioteka tego wymaga

app = FastAPI(lifespan=lifespan)

@app.get("/lucky-number")
def lucky_number(request: Request):
    info = get_student_information(request.app.state.client)
    return {"lucky_number": info.lucky_number}