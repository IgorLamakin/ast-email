// Достаёт версию из electron/package.json и соответствующий ей текст из
// CHANGELOG.md - чтобы release.bat мог сам сформировать осмысленное сообщение
// для commit'а в Git, не спрашивая пользователя ничего вручную.
const fs = require('fs')
const path = require('path')

const pkg = JSON.parse(fs.readFileSync(path.join(__dirname, '..', 'electron', 'package.json'), 'utf8'))
const version = pkg.version

const changelogPath = path.join(__dirname, '..', 'CHANGELOG.md')
let message = `Версия ${version}`

if (fs.existsSync(changelogPath)) {
  const content = fs.readFileSync(changelogPath, 'utf8')
  const marker = `## v${version}`
  const startIdx = content.indexOf(marker)
  if (startIdx !== -1) {
    const afterHeader = content.indexOf('\n', startIdx) + 1
    const nextSectionIdx = content.indexOf('\n## v', afterHeader)
    const section = (nextSectionIdx === -1 ? content.slice(afterHeader) : content.slice(afterHeader, nextSectionIdx)).trim()
    if (section) {
      // Git commit message: первая строка - краткая, остальное - тело коммита.
      message = `v${version}\n\n${section}`
    }
  }
}

console.log(version)
fs.writeFileSync(path.join(__dirname, '.commit-message.tmp'), message, 'utf8')
