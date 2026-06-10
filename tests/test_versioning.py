import io


def test_document_version_upload_and_conflict(client, auth_headers):
    files = {"file": ("hello.txt", io.BytesIO(b"first version"), "text/plain")}

    create_resp = client.post("/upload", headers=auth_headers, files=files)
    assert create_resp.status_code == 200
    first_doc = create_resp.json()
    assert first_doc["version_number"] == 1
    assert first_doc["group_id"]

    # Upload a second version using the current expected version id.
    second_files = {"file": ("hello.txt", io.BytesIO(b"second version"), "text/plain")}
    version_resp = client.post(
        f"/documents/{first_doc['id']}/versions",
        headers=auth_headers,
        data={"expected_version_id": first_doc["id"]},
        files=second_files,
    )
    assert version_resp.status_code == 200
    second_doc = version_resp.json()
    assert second_doc["version_number"] == 2
    assert second_doc["group_id"] == first_doc["group_id"]

    # Old version should no longer be current.
    old_doc_resp = client.get(f"/documents/{first_doc['id']}", headers=auth_headers)
    assert old_doc_resp.status_code == 200
    assert old_doc_resp.json()["is_current"] is False

    list_resp = client.get("/documents", headers=auth_headers)
    assert list_resp.status_code == 200
    current_docs = list_resp.json()
    assert any(doc["id"] == second_doc["id"] for doc in current_docs)
    assert all(doc["version_number"] == 2 or doc["id"] != second_doc["id"] for doc in current_docs)

    # Conflict when uploading against a stale version reference.
    conflict_resp = client.post(
        f"/documents/{first_doc['id']}/versions",
        headers=auth_headers,
        data={"expected_version_id": first_doc["id"]},
        files={"file": ("hello.txt", io.BytesIO(b"third version"), "text/plain")},
    )
    assert conflict_resp.status_code == 409
    conflict_body = conflict_resp.json()
    assert conflict_body["detail"]["current_version_id"] == second_doc["id"]
