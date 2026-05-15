import jsPDF from 'jspdf'
import { flattenQuestions, sectionLabels, sectionOrder, standardInstructions } from './questionPaperFormat'

export function downloadPaperPdf(paperEntry) {
  const questions = flattenQuestions(paperEntry, { numbering: 'global' })
  const doc = new jsPDF({ unit: 'pt', format: 'a4' })
  const marginLeft = 40
  const pageHeight = doc.internal.pageSize.getHeight()
  let y = 50

  const writeLine = (text, opts = {}) => {
    const fontSize = opts.fontSize || 11
    const gap = opts.gap || 16
    doc.setFont('helvetica', opts.bold ? 'bold' : 'normal')
    doc.setFontSize(fontSize)
    const lines = doc.splitTextToSize(String(text ?? ''), 515)
    for (const line of lines) {
      if (y > pageHeight - 40) {
        doc.addPage()
        y = 40
      }
      doc.text(line, marginLeft, y)
      y += gap
    }
  }

  const paperTitle = paperEntry.paper_name || paperEntry.topic || 'Question Paper'
  writeLine(paperTitle, { fontSize: 16, bold: true, gap: 20 })
  writeLine(`Mode: ${paperEntry.mode || 'official'}`, { fontSize: 11 })
  writeLine(`Total Marks: ${paperEntry.total_marks || 0}`, { fontSize: 11 })
  writeLine(`Generated: ${new Date(paperEntry.created_at || Date.now()).toLocaleString()}`, { fontSize: 11, gap: 18 })
  writeLine('Instructions:', { fontSize: 11, bold: true, gap: 16 })
  standardInstructions().forEach((line) => writeLine(`- ${line}`, { fontSize: 10, gap: 14 }))
  writeLine('', { gap: 10 })

  for (const sectionKey of sectionOrder) {
    const sectionQuestions = questions.filter((question) => question.section === sectionKey)
    if (!sectionQuestions.length) continue

    const sectionTotal = sectionQuestions.reduce((sum, row) => sum + (row.marks || 0), 0)
    const heading = `${sectionLabels[sectionKey]} (${sectionTotal} marks)`
    writeLine(heading, { fontSize: 12, bold: true, gap: 18 })

    sectionQuestions.forEach((question) => {
      writeLine(`${question.number}. ${question.question} (${question.marks} marks)`, { fontSize: 11, bold: true, gap: 16 })
      if (question.section === 'mcq' && question.options.length) {
        question.options.forEach((opt, optionIdx) => {
          const label = String.fromCharCode(65 + optionIdx)
          writeLine(`   ${label}. ${opt}`, { fontSize: 10, gap: 14 })
        })
      }
      writeLine('', { gap: 10 })
    })
  }

  const safeTitle = String(paperTitle).replace(/[^a-z0-9-_]+/gi, '-').slice(0, 60)
  doc.save(`${safeTitle || 'question-paper'}.pdf`)
}
