import webview
import tkinter as tk
from threading import Thread
from screeninfo import get_monitors

class ConfigPanel(tk.Toplevel):
    def __init__(self, master):
        super().__init__(master)
        self.attributes('-fullscreen', True)  # Abrir en pantalla completa
        self.overrideredirect(True)  # Eliminar borde de la ventana
        self.attributes('-topmost', True)  # Mantener la ventana siempre al frente

        close_button = tk.Button(self, text="X", command=self.close_panel)
        close_button.pack(side=tk.TOP, anchor=tk.NE, padx=10, pady=10)

        label = tk.Label(self, text="Configuraciones Locales", font=('Arial', 24))
        label.pack(pady=20)

        self.entry = tk.Entry(self, font=('Arial', 16))
        self.entry.pack(pady=10)

        save_button = tk.Button(self, text="Guardar", command=self.save_config)
        save_button.pack(pady=10)

    def save_config(self):
        config_value = self.entry.get()
        print(f"Configuración guardada: {config_value}")
        self.close_panel()

    def close_panel(self):
        self.destroy()

def open_config_panel():
    root = tk.Tk()
    root.withdraw()  # Ocultar la ventana principal de Tkinter
    ConfigPanel(root).mainloop()

class Api:
    def open_config(self):
        config_thread = Thread(target=open_config_panel)
        config_thread.start()

def add_button(window):
    # Crear un botón flotante en la ventana de webview
    js_code = """
        var button = document.createElement('button');
        button.innerText = 'Configuraciones Locales';
        button.style.position = 'fixed';
        button.style.bottom = '20px';
        button.style.right = '20px';
        button.style.padding = '10px 20px';
        button.style.backgroundColor = '#007BFF';
        button.style.color = '#FFF';
        button.style.border = 'none';
        button.style.borderRadius = '5px';
        button.style.cursor = 'pointer';
        button.style.zIndex = '1000';
        button.onclick = function() {
            window.pywebview.api.open_config();
        };
        document.body.appendChild(button);
    """
    window.evaluate_js(js_code)

if __name__ == '__main__':
    # Obtener la resolución de la pantalla principal
    monitor = get_monitors()[0]
    width, height = monitor.width, monitor.height

    # Crear la instancia de la API
    api = Api()

    # Crear la ventana de webview con las dimensiones especificadas y sin bordes
    window = webview.create_window(
        'Filtrar Chat de WhatsApp',
        'http://airtekapp.ddns.net/admin',
        width=width,
        height=height,
        resizable=False,
        fullscreen=True,
        frameless=False,
        js_api=api
    )

    # Agregar el botón después de cargar la página
    webview.start(add_button, window)
