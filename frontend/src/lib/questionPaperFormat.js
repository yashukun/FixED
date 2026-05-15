export const sectionOrder = ['mcq', 'subjective', 'true_false', 'fill_blank']

export const sectionLabels = {
  mcq: 'Section A - Multiple Choice Questions',
  subjective: 'Section B - Subjective Questions',
  true_false: 'Section C - True / False',
  fill_blank: 'Section D - Fill in the Blanks',
}

export const shortSectionLabels = {
  mcq: 'MCQ',
  subjective: 'Subjective',
  true_false: 'True / False',
  fill_blank: 'Fill in the Blank',
}

export function normalizePaperEntry(row) {
  if (!row) return null
  return {
    paper_id: row.paper_id,
    paper_name: row.paper_name || row.topic || 'Untitled paper',
    topic: row.topic || 'Untitled paper',
    mode: row.mode || 'official',
    file_id: row.file_id || '',
    total_marks: Number(row.total_marks || 0),
    created_at: row.created_at || new Date().toISOString(),
    paper: row.paper || { mcq: [], subjective: [], true_false: [], fill_blank: [] },
  }
}

export function flattenQuestions(paperEntry, { numbering = 'global' } = {}) {
  if (!paperEntry?.paper) return []
  const rows = []
  let globalCounter = 1
  for (const key of sectionOrder) {
    const sectionRows = Array.isArray(paperEntry.paper[key]) ? paperEntry.paper[key] : []
    let sectionCounter = 1
    for (let idx = 0; idx < sectionRows.length; idx += 1) {
      const row = sectionRows[idx]
      const number = numbering === 'per_section' ? sectionCounter : globalCounter
      rows.push({
        qid: `${key}-${idx}`,
        number,
        globalNumber: globalCounter,
        section: key,
        sectionLabel: shortSectionLabels[key] || key,
        longSectionLabel: sectionLabels[key] || key,
        question: String(row?.question || ''),
        answer: String(row?.answer || ''),
        marks: Number(row?.marks || 0),
        options: Array.isArray(row?.options) ? row.options : [],
      })
      sectionCounter += 1
      globalCounter += 1
    }
  }
  return rows
}

export function standardInstructions() {
  return [
    'Read all questions carefully before answering.',
    'Attempt all questions unless instructed otherwise.',
    'Write concise and relevant answers.',
  ]
}
