from fastapi import FastAPI


app = FastAPI(title="AutoDesk")


@app.get("/")
def health():
    return {"status": "healthy"}
