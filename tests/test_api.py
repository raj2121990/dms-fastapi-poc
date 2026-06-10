import io


def test_upload_and_search_text_file(client, auth_headers):
    files = {"file": ("hello.txt", io.BytesIO(b"quick brown fox"), "text/plain")}

    r = client.post("/upload", headers=auth_headers, files=files)
    assert r.status_code == 200
    body = r.json()
    assert "id" in body
    assert body["status"] in ("processed", "pending")

    # search for a term we uploaded
    r2 = client.get("/search", headers=auth_headers, params={"q": "quick"})
    assert r2.status_code == 200
    results = r2.json()
    assert any(item["filename"] == "hello.txt" for item in results)


def test_shared_document_access(client, auth_headers):
    # Create a collaborator user and a document owned by admin.
    create_resp = client.post(
        "/users",
        headers=auth_headers,
        data={"username": "collab", "password": "collabpass", "role": "viewer"},
    )
    assert create_resp.status_code == 200

    token_resp = client.post(
        "/token",
        data={"username": "collab", "password": "collabpass"},
    )
    assert token_resp.status_code == 200
    collab_token = token_resp.json()["access_token"]
    collab_headers = {"Authorization": f"Bearer {collab_token}"}

    files = {"file": ("shared.txt", io.BytesIO(b"shared content"), "text/plain")}
    upload_resp = client.post("/upload", headers=auth_headers, files=files)
    assert upload_resp.status_code == 200
    document = upload_resp.json()

    share_resp = client.post(
        f"/documents/{document['id']}/share",
        headers=auth_headers,
        data={"username": "collab", "access_level": "read"},
    )
    assert share_resp.status_code == 200

    search_resp = client.get("/search", headers=collab_headers, params={"q": "shared"})
    assert search_resp.status_code == 200
    results = search_resp.json()
    assert any(item["id"] == document["id"] for item in results)

    download_resp = client.get(f"/download/{document['id']}", headers=collab_headers)
    assert download_resp.status_code == 200
    assert download_resp.content == b"shared content"
