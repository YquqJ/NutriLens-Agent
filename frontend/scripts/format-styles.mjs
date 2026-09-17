import { readdir, readFile, writeFile } from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { format } from 'prettier'

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../src')
const checkOnly = process.argv.includes('--check')
const stylePattern = /(<style\b[^>]*>)([\s\S]*?)(<\/style>)/g
const prettierOptions = {
  parser: 'scss',
  printWidth: 100,
  singleQuote: true,
}

async function collectFiles(directory) {
  const entries = await readdir(directory, { withFileTypes: true })
  const nested = await Promise.all(
    entries.map((entry) => {
      const entryPath = path.join(directory, entry.name)
      return entry.isDirectory() ? collectFiles(entryPath) : [entryPath]
    }),
  )
  return nested.flat()
}

function withLineEnding(value, lineEnding) {
  return value.replace(/\r?\n/g, lineEnding)
}

async function formatVueStyles(source) {
  const lineEnding = source.includes('\r\n') ? '\r\n' : '\n'
  const matches = [...source.matchAll(stylePattern)]
  if (!matches.length) return source

  let cursor = 0
  let result = ''

  for (const match of matches) {
    const index = match.index ?? 0
    const formatted = (await format(match[2].trim(), prettierOptions)).trimEnd()
    result += source.slice(cursor, index)
    result += `${match[1]}${lineEnding}${withLineEnding(formatted, lineEnding)}${lineEnding}${match[3]}`
    cursor = index + match[0].length
  }

  return result + source.slice(cursor)
}

async function formatFile(filePath) {
  const source = await readFile(filePath, 'utf8')
  const formatted = filePath.endsWith('.vue')
    ? await formatVueStyles(source)
    : await format(source, prettierOptions)

  if (formatted === source) return false
  if (!checkOnly) await writeFile(filePath, formatted, 'utf8')
  return true
}

const files = (await collectFiles(root)).filter(
  (filePath) => filePath.endsWith('.vue') || filePath.endsWith('.scss'),
)
const changed = []

for (const filePath of files) {
  if (await formatFile(filePath)) changed.push(path.relative(root, filePath))
}

if (checkOnly && changed.length) {
  console.error('Style formatting required:')
  changed.forEach((filePath) => console.error(`- ${filePath}`))
  process.exitCode = 1
} else {
  const action = checkOnly ? 'checked' : 'formatted'
  console.log(`${action} ${files.length} style files; ${changed.length} changed`)
}
