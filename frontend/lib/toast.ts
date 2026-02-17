type ToastType = "error" | "success" | "info"
type ToastHandler = (msg: string, type: ToastType) => void

let _handler: ToastHandler | null = null

export const toast = {
  error:   (msg: string) => _handler?.(msg, "error"),
  success: (msg: string) => _handler?.(msg, "success"),
  info:    (msg: string) => _handler?.(msg, "info"),
  _register:   (fn: ToastHandler) => { _handler = fn },
  _unregister: () => { _handler = null },
}
