const BACKEND_URL = process.env.FASTAPI_URL ?? "http://localhost:8000"

export async function GET(req: Request) {
  const upstream = await fetch(`${BACKEND_URL}/api/regulations/sources`, {
    method: "GET",
    headers: {
      "Content-Type": "application/json",
    },
    signal: req.signal,
  })

  const headers = new Headers()
  const contentType = upstream.headers.get("Content-Type") ?? "application/json"
  headers.set("Content-Type", contentType)

  return new Response(upstream.body, {
    status: upstream.status,
    headers,
  })
}

export async function POST(req: Request) {
  const body = await req.text()

  const upstream = await fetch(`${BACKEND_URL}/api/regulations/sources`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body,
    signal: req.signal,
  })

  const headers = new Headers()
  const contentType = upstream.headers.get("Content-Type") ?? "application/json"
  headers.set("Content-Type", contentType)

  return new Response(upstream.body, {
    status: upstream.status,
    headers,
  })
}
