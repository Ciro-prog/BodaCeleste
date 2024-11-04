import webview

if __name__ == '__main__':
    # Dimensiones de la pantalla de un iPhone 11 Pro Max
    iphone_11_pro_max_width = 1242 // 3  # dividir por 3 para adecuarlo a DPI estándar
    iphone_11_pro_max_height = 2688 // 3  # dividir por 3 para adecuarlo a DPI estándar

    # Crear la ventana con las dimensiones especificadas y sin bordes
    window = webview.create_window(
        'Casamiento', 
        'http://airtekapp.ddns.net/', 
        width=iphone_11_pro_max_width, 
        height=iphone_11_pro_max_height, 
        resizable=False,
        fullscreen=False
    )

    # Iniciar la ventana
    webview.start()
