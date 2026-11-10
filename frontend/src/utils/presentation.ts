// Start the native fullscreen request during the navigation click, while browser activation is available.
export async function enterPresentationFullscreen(event?: MouseEvent): Promise<boolean> {
  if (event && (event.ctrlKey || event.metaKey || event.shiftKey || event.altKey || event.button !== 0)) return false;
  if (document.fullscreenElement) return true;
  if (!document.fullscreenEnabled) return false;
  try {
    await document.documentElement.requestFullscreen();
    return true;
  } catch {
    return false;
  }
}

export async function exitPresentationFullscreen() {
  if (document.fullscreenElement === document.documentElement) {
    await document.exitFullscreen().catch(() => {});
  }
}
