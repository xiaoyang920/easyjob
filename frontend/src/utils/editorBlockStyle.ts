import { Boot, DomEditor, SlateEditor, SlateElement, SlateTransforms, type IDomEditor, type ISelectMenu } from '@wangeditor/editor'

export const blockStyleMenuKey = 'articleBlockStyle'
const headingTypes = ['header1', 'header2', 'header3', 'header4', 'header5']
const textBlockTypes = new Set(['paragraph', ...headingTypes, 'list-item', 'todo', 'blockquote'])
type ArticleTextBlock = SlateElement & { type: string; ordered?: boolean; level?: number; checked?: boolean }
let registered = false

/** A block format changes the whole paragraph/list item, preserving its inline marks and links. */
class ArticleBlockStyleMenu implements ISelectMenu {
  readonly title = '正文与标题'
  readonly tag = 'select'
  readonly width = 86
  readonly selectPanelWidth = 160

  getValue(editor: IDomEditor): string {
    const blocks = [...SlateEditor.nodes(editor, {
      match: node => SlateElement.isElement(node) && textBlockTypes.has(DomEditor.getNodeType(node)),
      mode: 'lowest',
    })]
    const type = blocks.length ? DomEditor.getNodeType(blocks[0]![0]) : ''
    return headingTypes.includes(type) && blocks.every(([node]) => DomEditor.getNodeType(node) === type) ? type : 'paragraph'
  }

  getOptions(editor: IDomEditor) {
    const value = this.getValue(editor)
    return [
      { value: 'paragraph', text: '正文' },
      ...headingTypes.map((type, index) => ({ value: type, text: `${['一级', '二级', '三级', '四级', '五级'][index]}标题` })),
    ].map(option => ({ ...option, selected: option.value === value }))
  }

  isActive(): boolean { return false }

  isDisabled(editor: IDomEditor): boolean {
    if (!editor.selection || editor.isDisabled()) return true
    const blocks = DomEditor.getSelectedElems(editor).filter(node => SlateEditor.isBlock(editor, node))
    // Never flatten a table, code block, image or other structural element.
    return !blocks.length || blocks.some(node => !textBlockTypes.has(DomEditor.getNodeType(node)) || editor.isVoid(node))
  }

  exec(editor: IDomEditor, value: string | boolean): void {
    if (typeof value !== 'string' || !['paragraph', ...headingTypes].includes(value) || this.isDisabled(editor)) return
    SlateEditor.withoutNormalizing(editor, () => {
      SlateTransforms.setNodes<ArticleTextBlock>(editor, {
        type: value,
        ordered: undefined,
        level: undefined,
        checked: undefined,
      }, {
        match: node => SlateElement.isElement(node) && textBlockTypes.has(DomEditor.getNodeType(node)),
        mode: 'lowest',
      })
    })
    editor.hidePanelOrModal()
  }
}

export function registerArticleBlockStyle(): void {
  if (registered) return
  Boot.registerMenu({ key: blockStyleMenuKey, factory: () => new ArticleBlockStyleMenu() })
  registered = true
}
