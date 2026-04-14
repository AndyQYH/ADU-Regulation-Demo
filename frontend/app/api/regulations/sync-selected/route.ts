const BACKEND_URL = process.env.FASTAPI_URL ?? "http://localhost:8000"

export async function POST(req: Request) {
  const body = await req.text()

  try {
    const upstream = await fetch(`${BACKEND_URL}/api/regulations/sync-selected`, {
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
  } catch {
    return Response.json(
      {
        selected: [],
        results: [],
        error: "Backend unavailable",
      },
      { status: 503 }
    )
  }
}
