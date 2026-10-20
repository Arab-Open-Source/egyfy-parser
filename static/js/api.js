const JSON_HEADERS = { "Content-Type": "application/json" };

async function errorMessage(response) {
  try {
    const payload = await response.json();
    if (payload && typeof payload.error === "string") {
      return payload.error;
    }
  } catch (error) {
    // Fall through to the status-based message.
  }
  return `Request failed (${response.status}).`;
}

async function request(path, options) {
  const response = await fetch(path, options);
  if (!response.ok) {
    throw new Error(await errorMessage(response));
  }
  return response;
}

export async function getInfo() {
  return (await request("api/info")).json();
}

export async function uploadFile(file) {
  const query = `name=${encodeURIComponent(file.name)}`;
  return (await request(`api/upload?${query}`, { method: "POST", body: file })).json();
}

export async function readPage(documentId, index, options) {
  const response = await request("api/page", {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify({ id: documentId, n: index, opts: options }),
  });
  return response.json();
}

export async function exportDocument(documentId, format, options, pages = null) {
  const payload = { id: documentId, format, opts: options };
  if (pages) {
    payload.pages = pages;
  }
  return request("api/export", {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify(payload),
  });
}
