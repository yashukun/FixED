const GATEWAY_API = import.meta.env.VITE_GATEWAY_API || '/api/gateway';
const INGEST_API = import.meta.env.VITE_INGEST_API || '/api/ingest';
const SEARCH_API = import.meta.env.VITE_SEARCH_API || '/api/search';

const parseJsonSafe = async (res) => {
  try {
    return await res.json();
  } catch {
    return null;
  }
};

const getErrorMessage = async (res, fallback) => {
  const json = await parseJsonSafe(res);
  if (json?.detail) return json.detail;
  if (json?.message) return json.message;

  try {
    const text = await res.text();
    if (text?.trim()) return text.trim();
  } catch {
    // Ignore and fall back
  }

  return fallback;
};

export const api = {
  getDashboardNav: async () => {
    const res = await fetch(`${GATEWAY_API}/dashboard/nav`);
    if (!res.ok) throw new Error(await getErrorMessage(res, 'Failed to fetch dashboard nav'));
    return res.json();
  },

  getDashboardOverview: async () => {
    const res = await fetch(`${GATEWAY_API}/dashboard/overview`);
    if (!res.ok) throw new Error(await getErrorMessage(res, 'Failed to fetch dashboard overview'));
    return res.json();
  },

  getLearnBooks: async () => {
    const res = await fetch(`${GATEWAY_API}/learn/books`);
    if (!res.ok) throw new Error(await getErrorMessage(res, 'Failed to fetch books'));
    return res.json();
  },

  getLearnSubjects: async () => {
    const res = await fetch(`${GATEWAY_API}/learn/subjects`);
    if (!res.ok) throw new Error(await getErrorMessage(res, 'Failed to fetch subjects'));
    return res.json();
  },

  getUpcomingEvents: async () => {
    const res = await fetch(`${GATEWAY_API}/upcoming/events`);
    if (!res.ok) throw new Error(await getErrorMessage(res, 'Failed to fetch upcoming events'));
    return res.json();
  },

  // Upload a document
  uploadBook: async (file) => {
    const formData = new FormData();
    formData.append('file', file);

    const res = await fetch(`${INGEST_API}/upload`, {
      method: 'POST',
      body: formData,
    });
    
    if (!res.ok) {
      throw new Error(await getErrorMessage(res, 'Upload failed'));
    }
    return res.json();
  },

  // Check job status
  getJobStatus: async (jobId) => {
    const res = await fetch(`${INGEST_API}/job/${jobId}`);
    if (!res.ok) throw new Error(await getErrorMessage(res, 'Failed to fetch job status'));
    return res.json();
  },

  // Get all uploaded books
  getAllJobs: async () => {
    const res = await fetch(`${INGEST_API}/jobs`);
    if (!res.ok) throw new Error(await getErrorMessage(res, 'Failed to fetch library'));
    return res.json();
  },

  getBookChapters: async (jobId) => {
    const res = await fetch(`${INGEST_API}/job/${jobId}/chapters`);
    if (!res.ok) throw new Error(await getErrorMessage(res, 'Failed to fetch chapters'));
    return res.json();
  },

  getBookFileUrl: (jobId) => `${INGEST_API}/job/${jobId}/file`,

  // Search within a specific book
  searchBook: async (query, fileId, opts = {}) => {
    const payload = {
      query,
      file_id: fileId,
      top_k: opts.topK ?? 5,
      active_page: opts.activePage ?? null,
      chapter_number: opts.chapterNumber ?? null,
    };
    const res = await fetch(`${SEARCH_API}/search`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(payload),
    });

    if (!res.ok) {
      throw new Error(await getErrorMessage(res, 'Search failed'));
    }
    return res.json();
  },
};
