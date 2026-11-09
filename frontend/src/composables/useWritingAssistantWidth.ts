import { useResizablePanelWidth } from './useResizablePanelWidth'

const storageKey = 'easyjob:writing-assistant-width'
export const defaultWritingAssistantWidth = 424

export function useWritingAssistantWidth() {
  // Leave at least 600px for writing plus the gap and outer panel inset.
  return useResizablePanelWidth({ storageKey, defaultWidth: defaultWritingAssistantWidth, reservedWidth: 632 })
}
