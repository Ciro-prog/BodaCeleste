from flask import Flask, request, redirect, url_for, render_template, jsonify, send_from_directory
from bson import ObjectId  # Para manejar correctamente los ObjectId de MongoDB
from werkzeug.utils import secure_filename
from flask_pymongo import PyMongo
import os
from flask_socketio import SocketIO, emit
import threading
import time
import uuid
import random
from datetime import datetime
from pymongo import DESCENDING
from PIL import Image, ExifTags

app = Flask(__name__)
app.config["MONGO_URI"] = "mongodb://localhost:27017/celeste"
app.config['SECRET_KEY'] = '6b9e7e5e7b24a2b912bb2352f4a91b4c64b8123c1b2af9b7caffad3a9dbb2a60'
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024
mongo = PyMongo(app)
socketio = SocketIO(app, cors_allowed_origins="*")
UPLOAD_FOLDER = 'uploads' 

BACKGROUND_FOLDER = 'background'
app.config['BACKGROUND_FOLDER'] = BACKGROUND_FOLDER

if not os.path.exists(BACKGROUND_FOLDER):
    os.makedirs(BACKGROUND_FOLDER)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/checkuser', methods=['GET'])
def check_user():
    user_id = request.cookies.get('user_id')
    if not user_id:
        return jsonify({"exists": False, "message": "No user_id cookie found"}), 404

    user = mongo.db.users.find_one({"_id": user_id})
    if not user:
        return jsonify({"exists": False, "message": "User does not exist"}), 404

    return jsonify({"exists": True, "message": "User exists", "user": user}), 200

@app.route('/upload', methods=['POST'])
def upload_file():
    file = request.files['file']
    if file and file.filename != '':
        # Genera un nombre de archivo único añadiendo un UUID
        extension = os.path.splitext(file.filename)[1]  # Obtiene la extensión del archivo
        unique_filename = str(uuid.uuid4()) + extension  # Crea un nombre de archivo único

        filename = secure_filename(unique_filename)
        file_path = os.path.join('uploads', filename)
        file.save(file_path)  # Guarda el archivo en el directorio 'uploads'
        
        # Procesa la imagen para asegurar que sea vertical y añade bordes negros si es necesario
        process_image(file_path)

        return jsonify({'message': 'Archivo subido con éxito', 'filename': filename}), 200
    return jsonify({'error': 'No se subió ningún archivo'}), 400



def process_image(image_path):
    with Image.open(image_path) as img:
        # Corrige la orientación de la imagen según los datos EXIF
        try:
            for orientation in ExifTags.TAGS.keys():
                if ExifTags.TAGS[orientation] == 'Orientation':
                    break
            exif = img._getexif()
            if exif is not None:
                orientation = exif.get(orientation)
                if orientation == 3:
                    img = img.rotate(180, expand=True)
                elif orientation == 6:
                    img = img.rotate(270, expand=True)
                elif orientation == 8:
                    img = img.rotate(90, expand=True)
        except (AttributeError, KeyError, IndexError):
            # No se encontraron datos EXIF, se omite la corrección
            pass
        
        width, height = img.size

        if width > height or width == height:
            # Añadir bordes negros para imágenes horizontales o cuadradas
            new_height = int(width * 1.5)  # Aumentar el lienzo en un 50% en altura
            new_img = Image.new("RGB", (width, new_height), "black")
            new_img.paste(img, (0, (new_height - height) // 2))
        else:
            # Para imágenes verticales, mantener la orientación sin bordes negros
            new_img = img

        new_img.save(image_path)


@app.route('/register', methods=['POST'])
def register_user():
    user_data = request.get_json()
    user_id = request.cookies.get('user_id', None)
    if not user_id:
        # Si no hay user_id, asignamos uno nuevo
        user_id = str(uuid.uuid4())
        avatar_number = random.randint(1, 50)  # Asignar un número de avatar aleatorio

        # Guardar o actualizar el nombre del usuario y su avatar en la base de datos
        mongo.db.users.update_one(
            {'_id': user_id},
            {'$set': {'name': user_data['name'], 'avatar_number': avatar_number}},
            upsert=True
        )

        response = jsonify({'message': 'Usuario registrado con éxito'})
        response.set_cookie('user_id', user_id, max_age=31536000)  # Expira en un año
    else:
        # Si el usuario ya está registrado, solo actualizamos el nombre si es necesario
        mongo.db.users.update_one({'_id': user_id}, {'$set': {'name': user_data['name']}})
        response = jsonify({'message': 'Nombre de usuario actualizado'})

    return response

@app.route('/post-comment', methods=['POST'])
def post_comment():
    data = request.get_json()
    user_id = request.cookies.get('user_id')
    
    # Verificar que el usuario está autenticado
    if not user_id:
        return jsonify({"error": "Usuario no autenticado"}), 403

    user = mongo.db.users.find_one({"_id": user_id})
    if not user:
        return jsonify({"error": "Usuario no encontrado"}), 404

    comment = {
        "userId": user_id,
        "imageId": data['image_id'],
        "userName": user['name'],  # Usar el nombre de la base de datos
        "text": data['text'],
        "timePosted": datetime.utcnow()
    }
    
    mongo.db.imgComments.insert_one(comment)

    # Emitir evento de nuevo comentario
    socketio.emit('new_comment', {
        "imageId": data['image_id'],
        "comment": {
            "userName": user['name'],
            "text": data['text'],
            "avatar": f"static/avatars/avatar{user.get('avatar_number', 1)}.png",
            "timeAgo": "justo ahora"
        }
    })

    return jsonify({
        "message": "Comentario publicado exitosamente",
        "userName": user['name'],  # Incluir el nombre de usuario en la respuesta
        "avatar": f"static/avatars/avatar{user.get('avatar_number', 1)}.png"  # Asumiendo que cada usuario tiene un número de avatar asignado
    }), 200



@app.route('/check-likes', methods=['POST'])
def check_likes():
    user_id = request.cookies.get('user_id')
    image_id = request.json['image_id']
    like = mongo.db.likes.find_one({'user_id': user_id, 'image_id': image_id})
    return jsonify({'liked': bool(like)})


@app.route('/like', methods=['POST'])
def like_image():
    user_id = request.cookies.get('user_id')
    image_id = request.json['image_id']
    # Comprobar si el usuario ya dio like a esta imagen
    existing_like = mongo.db.likes.find_one({'user_id': user_id, 'image_id': image_id})
    if not existing_like:
        mongo.db.likes.insert_one({'user_id': user_id, 'image_id': image_id})

        # Obtener el nuevo recuento de likes
        likes_count = mongo.db.likes.count_documents({'image_id': image_id})

        # Emitir evento de nuevo like
        socketio.emit('new_like', {
            'imageId': image_id,
            'likes': likes_count,
            'user': mongo.db.users.find_one({'_id': user_id})['name']
        })

        return jsonify({'liked': True, 'likes': likes_count})
    else:
        # Opcionalmente puedes manejar "dislike" aquí
        mongo.db.likes.delete_one({'_id': existing_like['_id']})
        likes_count = mongo.db.likes.count_documents({'image_id': image_id})

        # Emitir evento de dislike
        socketio.emit('new_like', {
            'imageId': image_id,
            'likes': likes_count,
            'user': None
        })

        return jsonify({'liked': False, 'likes': likes_count})

@app.route('/fotos')
def fotos():
    return render_template('fotos.html')

@app.route('/admin/style.css')
def admin_style():
    return app.send_static_file('style.css')

@app.route('/uploads', methods=['GET'])
def list_images():
    images = sorted(os.listdir(UPLOAD_FOLDER), key=lambda x: os.path.getmtime(os.path.join(UPLOAD_FOLDER, x)), reverse=True)
    return jsonify(images)

@app.route('/galery')
def galery():
    return render_template('galery.html')
@app.route('/regalos')
def regalos():
    return render_template('regalos.html')

@app.route('/ubicacion')
def ubicacion():
    return render_template('ubicacion.html')


@app.route('/uploads-galery', methods=['GET'])
def list_images_galery():
    images = sorted(
        os.listdir(UPLOAD_FOLDER),
        key=lambda x: os.path.getmtime(os.path.join(UPLOAD_FOLDER, x)),
        reverse=True
    )
    image_data = []
    for image in images:
        image_path = os.path.join(UPLOAD_FOLDER, image)
        
        # Obtener los likes y los datos del usuario que dio like
        image_likes = mongo.db.likes.find({'image_id': image})
        like_users = [user['name'] for like in image_likes if (user := mongo.db.users.find_one({'_id': like['user_id']}))]
        random_like_user = random.choice(like_users) if like_users else None

        # Recuperar comentarios de la base de datos, ordenados descendentemente por 'timePosted'
        comments = []
        img_comments = mongo.db.imgComments.find({'imageId': image}).sort('timePosted', DESCENDING)
        for comment in img_comments:
            user = mongo.db.users.find_one({'_id': comment['userId']})
            if user:
                avatar = f"static/avatars/avatar{user.get('avatar_number', 1)}.png"
                time_ago = calculate_time_ago(comment['timePosted'])
                comments.append({
                    "userName": user['name'],
                    "text": comment['text'],
                    "avatar": avatar,
                    "timeAgo": time_ago
                })
            else:
                comments.append({
                    "userName": "Desconocido",
                    "text": comment['text'],
                    "avatar": 'default_avatar.png',
                    "timeAgo": calculate_time_ago(comment['timePosted'])
                })

        # Agregar datos relevantes para cada imagen
        image_data.append({
            'imageId': image,
            'imageUrl': url_for('uploaded_file', filename=image),
            'likes': len(like_users),
            'randomLikeUser': random_like_user,
            'comments': comments
        })
    return jsonify(image_data)

def calculate_time_ago(time_posted):
    # Función para calcular cuánto tiempo ha pasado desde que se publicó el comentario
    now = datetime.utcnow()
    diff = now - time_posted
    if diff.days > 0:
        return f"hace {diff.days} días"
    elif diff.seconds // 3600 > 0:
        return f"hace {diff.seconds // 3600} horas"
    elif diff.seconds // 60 > 0:
        return f"hace {diff.seconds // 60} minutos"
    else:
        return "hace unos momentos"



@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(UPLOAD_FOLDER, filename)


@app.route('/invitados')
def invitados():
    return render_template('invitados.html')

@app.route('/configs')
def configs():
    return render_template('configs.html')

@app.route('/api/invitados', methods=['GET'])
def api_invitados():
    nombre = request.args.get('nombre', '')
    if nombre:
        invitados = mongo.db.invitados.find({"nombre": {"$regex": nombre, "$options": "i"}})
    else:
        invitados = mongo.db.invitados.find()
    # Asegúrate de incluir email y telefono en la respuesta, además del nombre y el ID
    return jsonify([
        {
            "_id": str(invitado['_id']),
            "nombre": invitado.get('nombre', 'No especificado'),
            "email": invitado.get('email', 'No disponible'),
            "telefono": invitado.get('telefono', 'No disponible'),
            "confirmado": invitado.get('confirmado', False)  # Manejo del estado confirmado
        } for invitado in invitados
    ])

@app.route('/comments/<image_id>', methods=['GET'])
def get_comments(image_id):
    comments = mongo.db.imgComments.find({'imageId': image_id}).sort('timePosted', DESCENDING)
    comments_list = []
    for comment in comments:
        user = mongo.db.users.find_one({'_id': comment['userId']})
        if user:
            avatar = f"static/avatars/avatar{user.get('avatar_number', 1)}.png"
            time_ago = calculate_time_ago(comment['timePosted'])
            comments_list.append({
                "userName": user['name'],
                "text": comment['text'],
                "avatar": avatar,
                "timeAgo": time_ago
            })
        else:
            comments_list.append({
                "userName": "Desconocido",
                "text": comment['text'],
                "avatar": 'default_avatar.png',
                "timeAgo": calculate_time_ago(comment['timePosted'])
            })

    # Obtener los likes y los datos del usuario que dio like
    likes_count = mongo.db.likes.count_documents({'image_id': image_id})
    like_users = [user['name'] for like in mongo.db.likes.find({'image_id': image_id}) if (user := mongo.db.users.find_one({'_id': like['user_id']}))]
    random_like_user = random.choice(like_users) if like_users else None

    return jsonify({
        "comments": comments_list,
        "likes": likes_count,
        "randomLikeUser": random_like_user
    })


@app.route('/api/invitados/<id>', methods=['GET'])
def get_invitado(id):
    invitado = mongo.db.invitados.find_one({'_id': ObjectId(id)})
    if invitado:
        invitado['_id'] = str(invitado['_id'])  # Convertimos ObjectId a string para JSON
        return jsonify(invitado)
    return jsonify({"error": "Invitado no encontrado"}), 404

@app.route('/api/invitados', methods=['POST'])
def add_invitado():
    invitado = request.get_json()
    result = mongo.db.invitados.insert_one(invitado)
    invitado['_id'] = str(result.inserted_id)
    return jsonify(invitado), 201

@app.route('/api/invitados/<id>', methods=['PUT'])
def update_invitado(id):
    invitado_data = request.get_json()
    # Filtra los datos para evitar intentar actualizar campos que no han cambiado o son nulos
    update_data = {key: value for key, value in invitado_data.items() if value is not None}

    # Verifica primero si el invitado existe
    if mongo.db.invitados.find_one({'_id': ObjectId(id)}) is None:
        return jsonify({"error": "Invitado no encontrado"}), 404

    # Realiza la actualización solo si hay cambios
    result = mongo.db.invitados.update_one({'_id': ObjectId(id)}, {'$set': update_data})
    if result.modified_count == 0 and any(update_data.values()):
        return jsonify({"message": "No changes were made"}), 200
    elif result.modified_count > 0:
        return jsonify({"message": "Invitado actualizado"}), 200
    else:
        return jsonify({"error": "No se pudo actualizar el invitado"}), 404


@app.route('/api/invitados/<id>', methods=['DELETE'])
def delete_invitado(id):
    result = mongo.db.invitados.delete_one({'_id': ObjectId(id)})
    if result.deleted_count:
        return jsonify({"message": "Invitado eliminado"}), 200
    return jsonify({"error": "No se pudo eliminar el invitado"}), 404

@app.route('/api/confirmar_asistencia', methods=['POST'])
def confirmar_asistencia():
    invitado_id = request.json['id']
    resultado = mongo.db.invitados.update_one(
        {'_id': ObjectId(invitado_id)},
        {'$set': {'confirmado': True}}
    )
    if resultado.modified_count:
        invitado = mongo.db.invitados.find_one({'_id': ObjectId(invitado_id)})
        # Emitir a todos los clientes
        socketio.emit('update_attendance', {'id': str(invitado_id), 'confirmado': True, 'name': invitado['nombre']}, room=None)
        return jsonify({'success': True, 'message': 'Asistencia confirmada con éxito.'})
    else:
        return jsonify({'success': False, 'message': 'No se pudo confirmar la asistencia.'})

@app.route('/api/cancelar_asistencia', methods=['POST'])
def cancelar_asistencia():
    invitado_id = request.json['id']
    resultado = mongo.db.invitados.update_one(
        {'_id': ObjectId(invitado_id)},
        {'$set': {'confirmado': False}}
    )
    if resultado.modified_count:
        invitado = mongo.db.invitados.find_one({'_id': ObjectId(invitado_id)})
        # Emitir a todos los clientes
        socketio.emit('update_attendance', {'id': str(invitado_id), 'confirmado': False, 'name': invitado['nombre']}, room=None)
        return jsonify({'success': True, 'message': 'Asistencia cancelada con éxito.'})
    else:
        return jsonify({'success': False, 'message': 'No se pudo cancelar la asistencia.'})

@app.route('/api/verify_admin', methods=['POST'])
def verify_admin():
    data = request.get_json()
    admin_code = data.get('code')
    admin_record = mongo.db.administrador.find_one({'pass': admin_code})
    if admin_record:
        return jsonify({'success': True, 'message': 'Código verificado con éxito.'})
    else:
        return jsonify({'success': False, 'message': 'Código incorrecto.'})

@app.route('/admin')
def admin():
    return render_template('dashboard.html')

@app.route('/pc')
def pc():
    return render_template('pc.html')

# CRUD Comunicados
@app.route('/comunicados', methods=['POST'])
def create_comunicado():
    comunicado = {
        'titulo': request.json['titulo'],
        'contenido': request.json['contenido'],
        'estado': 'activo'  # estado inicial
    }
    comunicado_id = mongo.db.comunicados.insert_one(comunicado).inserted_id
    return jsonify({'id': str(comunicado_id)}), 201

@app.route('/api/comunicados_api', methods=['GET'])
def get_comunicados_api():
    comunicados = mongo.db.comunicados.find({'estado': 'activo'})
    result = [{
        'id': str(comunicado['_id']),
        'titulo': comunicado['titulo'],
        'contenido': comunicado['contenido'],
        'estado': comunicado['estado']
    } for comunicado in comunicados]
    return jsonify(result)


@app.route('/comunicados', methods=['GET'])
def get_comunicados():
    comunicados = mongo.db.comunicados.find()
    result = [{
        'id': str(comunicado['_id']),
        'titulo': comunicado['titulo'],
        'contenido': comunicado['contenido'],
        'estado': comunicado['estado']
    } for comunicado in comunicados]
    return jsonify(result)

@app.route('/comunicados/<id>', methods=['GET'])
def get_comunicado(id):
    comunicado = mongo.db.comunicados.find_one({'_id': ObjectId(id)})
    if comunicado:
        comunicado['_id'] = str(comunicado['_id'])  # Convertir ObjectId a string para JSON
        return jsonify(comunicado)
    else:
        return jsonify({'error': 'Comunicado no encontrado'}), 404


    mongo.db.comunicados.update_one({'_id': ObjectId(id)}, {'$set': update_data})
    return jsonify({'message': 'Comunicado actualizado'})

@app.route('/comunicados/<id>', methods=['DELETE'])
def delete_comunicado(id):
    result = mongo.db.comunicados.delete_one({'_id': ObjectId(id)})
    if result.deleted_count:
        return jsonify({'message': 'Comunicado eliminado'}), 200
    else:
        return jsonify({'error': 'Comunicado no encontrado'}), 404

@app.route('/comunicados/<id>', methods=['PUT'])
def update_comunicado(id):
    comunicado_data = request.get_json()
    update_data = {key: comunicado_data[key] for key in comunicado_data if comunicado_data[key] is not None}

    # Verifica primero si el comunicado existe
    if mongo.db.comunicados.find_one({'_id': ObjectId(id)}) is None:
        return jsonify({"error": "Comunicado no encontrado"}), 404

    result = mongo.db.comunicados.update_one({'_id': ObjectId(id)}, {'$set': update_data})
    if result.modified_count == 0 and any(comunicado_data.values()):
        return jsonify({"message": "No changes were made"}), 200
    elif result.modified_count > 0:
        return jsonify({"message": "Comunicado actualizado"}), 200
    else:
        return jsonify({"error": "No se pudo actualizar el comunicado"}), 404


@app.route('/api/info_event', methods=['GET', 'POST'])
def info_event():
    if request.method == 'GET':
        config = mongo.db.configs.find_one({}, {'infoEvent': 1, '_id': 0})
        return jsonify(config if config else {"infoEvent": ""}), 200
    else:  # POST para actualizar o limpiar la información del evento
        try:
            # Obtiene infoEvent de la solicitud, permite contenido vacío
            info_event_data = request.get_json().get('infoEvent', "").strip()
            # Actualiza o limpia infoEvent en la base de datos
            mongo.db.configs.update_one({}, {'$set': {'infoEvent': info_event_data}}, upsert=True)
            # Verifica si el contenido es vacío para responder apropiadamente
            if info_event_data:
                return jsonify({"message": "Información del evento actualizada con éxito"}), 200
            else:
                return jsonify({"message": "Información del evento ha sido limpiada"}), 200
        except Exception as e:
            # Captura cualquier otra excepción y devuelve un mensaje de error
            return jsonify({"error": str(e)}), 500


@app.route('/api/config', methods=['GET', 'POST'])
def config():
    if request.method == 'GET':
        config = mongo.db.configs.find_one({})
        if config:
            # Convertir ObjectId a string para que sea JSON serializable
            if '_id' in config:
                config['_id'] = str(config['_id'])
        print("Configuración cargada:", config)  # Imprime los datos recuperados
        return jsonify(config if config else {}), 200
    else:  # POST para actualizar o crear la configuración
        config_data = request.get_json()
        mongo.db.configs.update_one({}, {'$set': config_data}, upsert=True)
        return jsonify({"message": "Configuración actualizada"}), 200

@app.route('/api/upload_background', methods=['POST'])
def upload_background():
    file = request.files.get('backgroundImageAPP')
    update_data = {
        'eventoCoordX': request.form.get('eventoCoordX', ''),
        'eventoCoordY': request.form.get('eventoCoordY', ''),
        'iglesiaCoordX': request.form.get('iglesiaCoordX', ''),
        'iglesiaCoordY': request.form.get('iglesiaCoordY', ''),
        'titularCuenta': request.form.get('titularCuenta', ''),
        'cbu': request.form.get('cbu', ''),
        'alias': request.form.get('alias', '')
    }

    if file and allowed_file(file.filename):
        try:
            filename = secure_filename(file.filename)
            file_path = os.path.join(app.config['BACKGROUND_FOLDER'], filename)
            file.save(file_path)
            update_data['backgroundImage'] = file_path
        except Exception as e:
            print(e)  # Imprime el error en consola
            return jsonify({"error": "Error al guardar el archivo"}), 500

    try:
        mongo.db.configs.update_one({}, {'$set': update_data}, upsert=True)
        return jsonify({"message": "Configuración actualizada con éxito"}), 200
    except Exception as e:
        print(e)  # Imprime el error en consola
        return jsonify({"error": "Error al actualizar la configuración"}), 500



def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in {'png', 'jpg', 'jpeg', 'gif','webp'}

@app.route('/background/<filename>')
def background_file(filename):
    return send_from_directory(app.config['BACKGROUND_FOLDER'], filename)

# Vista para mostrar los comunicados
@app.route('/noticias')
def view_comunicados():
    return render_template('comunicados.html')

@app.route('/api/donate', methods=['POST'])
def donate():
    data = request.get_json()
    gift_id = data['giftId']
    donor_name = data['donorName']
    donation_amount = float(data['donationAmount'])
    payment_type = data['paymentType']
    gift_price = float(data['giftPrice'])  # Monto total del regalo desde el frontend

    # Buscar el regalo en la base de datos
    gift = mongo.db.gifts.find_one({'_id': gift_id})

    if gift:
        # Validar que la suma de la donación y lo ya pagado no exceda el monto total del regalo
        total_after_donation = gift.get('monto_total_pagado', 0) + donation_amount
        if total_after_donation > gift['monto_total']:
            return jsonify({'success': False, 'message': 'La donación excede el monto total permitido para el regalo.'}), 400

        # Validar que el monto de la donación no exceda el monto restante
        remaining_amount = gift['monto_total'] - gift.get('monto_total_pagado', 0)
        if donation_amount > remaining_amount:
            return jsonify({'success': False, 'message': 'La donación excede el monto restante del regalo.'}), 400

        # Validar que la donación sea al menos $30,000 a menos que el monto restante sea menor
        if donation_amount < 1 and remaining_amount > 1:
            return jsonify({'success': False, 'message': 'La donación debe ser de al menos $1.'}), 400

        # Actualizar el monto total donado y el monto restante
        new_total = gift.get('monto_total_pagado', 0) + donation_amount
        remaining_amount = gift['monto_total'] - new_total

        mongo.db.gifts.update_one(
            {'_id': gift_id},
            {'$set': {
                'monto_total_pagado': new_total,
                'monto_restante': max(0, remaining_amount)
            },
             '$push': {
                 'donaciones': {
                     'nombre': donor_name,
                     'monto': donation_amount,
                     'metodo_pago': payment_type,
                     'fecha': datetime.now()
                 }
             }
            }
        )
        return jsonify({'success': True}), 200
    else:
        # Si el regalo no existe, crear uno nuevo
        if donation_amount > gift_price:
            return jsonify({'success': False, 'message': 'La donación excede el monto total permitido para el regalo.'}), 400

        if donation_amount < 1 and gift_price > 1:
            return jsonify({'success': False, 'message': 'La donación debe ser de al menos $1.'}), 400

        remaining_amount = gift_price - donation_amount
        new_gift = {
            '_id': gift_id,
            'nombre': gift_id,  # Puedes cambiar esto si el ID no es el nombre
            'monto_total': gift_price,
            'monto_total_pagado': donation_amount,
            'monto_restante': max(0, remaining_amount),
            'donaciones': [
                {
                    'nombre': donor_name,
                    'monto': donation_amount,
                    'metodo_pago': payment_type,
                    'fecha': datetime.now()
                }
            ]
        }

        mongo.db.gifts.insert_one(new_gift)
        return jsonify({'success': True, 'message': 'Nuevo regalo creado y donación registrada'}), 201

    return jsonify({'success': False, 'message': 'Ocurrió un error al procesar la donación'}), 500


@app.route('/api/gift_percentage/<gift_id>', methods=['GET'])
def get_gift_percentage(gift_id):
    # Buscar el regalo en la base de datos
    gift = mongo.db.gifts.find_one({'_id': gift_id})
    
    if not gift:
        # Si el regalo no se encuentra, devolver porcentaje 0
        return jsonify({'success': True, 'percentage': 0, 'donatedAmount': 0}), 200

    monto_total = gift.get('monto_total', 0)
    monto_total_pagado = gift.get('monto_total_pagado', 0)

    if monto_total == 0:
        # Si no hay monto total definido, también devolver porcentaje 0
        return jsonify({'success': True, 'percentage': 0, 'donatedAmount': 0}), 200

    porcentaje = (monto_total_pagado / monto_total) * 100
    return jsonify({'success': True, 'percentage': porcentaje, 'donatedAmount': monto_total_pagado}), 200


@app.route('/donations', methods=['GET'])
def donations_view():
    # Obtener todas las donaciones de la base de datos
    gifts = mongo.db.gifts.find()

    # Preparar los datos para la vista
    donations_by_person = {}
    donations_by_gift = {}
    donations_over_time = []
    payment_methods = {"Efectivo": 0, "Transferencia": 0}
    gifts_with_no_donations = []
    total_donations = 0
    total_donors = 0

    for gift in gifts:
        gift_name = gift.get('nombre')
        total_gift_donations = 0
        donors_for_gift = set()

        for donation in gift.get('donaciones', []):
            donor_name = donation.get('nombre')
            donation_amount = int(donation.get('monto'))  # Convertir a entero
            donation_date = donation.get('fecha')
            payment_type = donation.get('metodo_pago')

            # Agrupar por persona
            if donor_name in donations_by_person:
                donations_by_person[donor_name]['total'] += donation_amount
                donations_by_person[donor_name]['gifts'].append({
                    'gift': gift_name,
                    'amount': donation_amount
                })
            else:
                donations_by_person[donor_name] = {
                    'total': donation_amount,
                    'gifts': [{
                        'gift': gift_name,
                        'amount': donation_amount
                    }]
                }

            # Agrupar por regalo
            if gift_name in donations_by_gift:
                donations_by_gift[gift_name] += donation_amount
            else:
                donations_by_gift[gift_name] = donation_amount

            # Actualizar métodos de pago
            payment_methods[payment_type] += donation_amount

            # Actualizar donaciones en el tiempo
            donations_over_time.append({
                'date': donation_date,
                'amount': donation_amount
            })

            total_gift_donations += donation_amount
            total_donations += donation_amount
            donors_for_gift.add(donor_name)

        if total_gift_donations == 0:
            gifts_with_no_donations.append(gift_name)

        total_donors = len(donations_by_person)

    # Encontrar el mayor donante y el regalo más donado
    top_donor = max(donations_by_person.items(), key=lambda x: x[1]['total']) if donations_by_person else None
    top_gift = max(donations_by_gift.items(), key=lambda x: x[1]) if donations_by_gift else None

    # Calcular promedio de donación por persona y convertir a entero
    avg_donation_per_person = int(total_donations / total_donors) if total_donors > 0 else 0

    # Convertir los totales de donaciones por persona a enteros
    for person in donations_by_person:
        donations_by_person[person]['total'] = int(donations_by_person[person]['total'])
        for gift in donations_by_person[person]['gifts']:
            gift['amount'] = int(gift['amount'])

    # Convertir los totales de donaciones por regalo a enteros
    donations_by_gift = {k: int(v) for k, v in donations_by_gift.items()}

    # Convertir los totales de métodos de pago a enteros
    payment_methods = {k: int(v) for k, v in payment_methods.items()}

    return render_template(
        'donations.html',
        donations_by_person=donations_by_person,
        donations_by_gift=donations_by_gift,
        top_donor=top_donor,
        top_gift=top_gift,
        payment_methods=payment_methods,
        donations_over_time=donations_over_time,
        gifts_with_no_donations=gifts_with_no_donations,
        avg_donation_per_person=avg_donation_per_person
    )


def format_currency(value):
    return f"${value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

@app.template_filter('currency')
def currency_filter(value):
    return format_currency(value)



if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000, debug=False)