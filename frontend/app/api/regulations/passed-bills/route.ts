const BACKEND_URL = process.env.FASTAPI_URL ?? "http://localhost:8000"

export async function GET(req: Request) {
  const url = new URL(req.url)
  const limit = url.searchParams.get("limit") ?? "50"

  const upstream = await fetch(
    `${BACKEND_URL}/api/regulations/passed-bills?limit=${encodeURIComponent(limit)}`,
    {
      method: "GET",
      signal: req.signal,
    }
  )

  const headers = new Headers()
  const contentType = upstream.headers.get("Content-Type") ?? "application/json"
  headers.set("Content-Type", contentType)

  return new Response(upstream.body, {
    status: upstream.status,
    headers,
  })
}
