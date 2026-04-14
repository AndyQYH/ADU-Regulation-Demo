const BACKEND_URL = process.env.FASTAPI_URL ?? "http://localhost:8000"

export async function GET(req: Request) {
  try {
    const upstream = await fetch(`${BACKEND_URL}/api/regulations/rag/status`, {
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
    return Response.json({
      total_chunks: 0,
      source_type_counts: {},
      is_ready: false,
    }, { status: 200 })
  }
}
