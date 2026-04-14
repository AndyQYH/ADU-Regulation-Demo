const BACKEND_URL = process.env.FASTAPI_URL ?? "http://localhost:8000"

export async function GET(req: Request) {
  const { searchParams } = new URL(req.url)
  const limit = searchParams.get("limit")
  const url = new URL(`${BACKEND_URL}/api/regulations/audit`)
  if (limit) {
    url.searchParams.set("limit", limit)
  }

  try {
    const upstream = await fetch(url.toString(), {
      method: "GET",
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
    return Response.json([], { status: 200 })
  }
}
