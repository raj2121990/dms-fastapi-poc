import io


def test_upload_and_search_text_file(client):
    data = {"owner": "tester"}
    files = {"file": ("hello.txt", io.BytesIO(b"quick brown fox"), "text/plain")}

    r = client.post("/upload", data=data, files=files)
    assert r.status_code == 200
    body = r.json()
    assert "id" in body
    assert body["status"] in ("processed", "pending")

    # search for a term we uploaded
    r2 = client.get("/search", params={"q": "quick"})
    assert r2.status_code == 200
    results = r2.json()
    assert any(item["filename"] == "hello.txt" for item in results)
