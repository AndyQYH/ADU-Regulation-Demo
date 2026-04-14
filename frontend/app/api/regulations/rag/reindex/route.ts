const BACKEND_URL = process.env.FASTAPI_URL ?? "http://localhost:8000"

export async function POST(req: Request) {
  const body = await req.text()

  try {
    const upstream = await fetch(`${BACKEND_URL}/api/regulations/rag/reindex`, {
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
        indexed_docs: 0,
        index_status: {
          total_chunks: 0,
          source_type_counts: {},
          is_ready: false,
        },
        error: "Backend unavailable",
      },
      { status: 503 }
    )
  }
}
