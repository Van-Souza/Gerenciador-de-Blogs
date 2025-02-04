from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
from pytz import timezone
brasilia_tz = timezone('America/Sao_Paulo')
import requests
import os
from functools import wraps

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///tasks.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = 'your-secret-key-here'
app.config['SYNC_URLS'] = [
    'https://meuatendimentovirtual.com.br/wp-json/wp/v2/docs?doc_category=35&per_page=100'
   # 'https://api2.example.com/docs',
    #'https://backup-api.example.com/data'
]  # Adicione/altere as URLs aqui
db = SQLAlchemy(app)

# Models
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password = db.Column(db.String(120), nullable=False)
    role = db.Column(db.String(20), nullable=False, default='reviewer')
    tasks = db.relationship('Task', backref='assignee', lazy=True)
    comments = db.relationship('TaskComment', backref='user', lazy=True)

class TaskComment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    task_id = db.Column(db.Integer, db.ForeignKey('task.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    message = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Task(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)      # Mantido
    status = db.Column(db.String(20), default='pending')   # Mantido
    priority = db.Column(db.Integer, default=3)            # Mantido
    deadline = db.Column(db.DateTime)                      # Mantido
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    assigned_to = db.Column(db.Integer, db.ForeignKey('user.id'))  # Mantido
    url = db.Column(db.String(500))                        # Mantido
    is_active = db.Column(db.Boolean, default=True)        # Mantido
    comments = db.relationship('TaskComment', backref='task', lazy=True, order_by='TaskComment.created_at')  # Mantido


# Login decorator
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# Routes
@app.route('/')
@login_required
def index():
    page = request.args.get('page', 1, type=int)
    per_page = 10
    
    query = Task.query.filter_by(is_active=True)
    
    # Apply filters
    status_filter = request.args.get('status')
    priority_filter = request.args.get('priority', type=int)
    search = request.args.get('search', '').strip()
    
    if status_filter:
        query = query.filter_by(status=status_filter)
    if priority_filter:
        query = query.filter_by(priority=priority_filter)
    if search:
        query = query.filter(Task.title.ilike(f'%{search}%'))
    
    if session.get('role') != 'admin':
        query = query.filter_by(assigned_to=session['user_id'])
    
    tasks = query.order_by(Task.priority.asc(), Task.deadline.asc())\
                .paginate(page=page, per_page=per_page, error_out=False)
    
    users = User.query.all() if session.get('role') == 'admin' else []
    
    return render_template('index.html', 
                         tasks=tasks,
                         users=users,
                         status_filter=status_filter,
                         priority_filter=priority_filter,
                         search=search)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = User.query.filter_by(username=username).first()
        
        if user and user.password == password:
            session['user_id'] = user.id
            session['username'] = user.username
            session['role'] = user.role
            return redirect(url_for('index'))
        
        flash('Credenciais inválidas', 'danger')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/task/update/<int:task_id>', methods=['POST'])
@login_required
def update_task(task_id):
    task = Task.query.get_or_404(task_id)
    
    if request.is_json:
        data = request.get_json()
        
        if session['role'] == 'admin' or task.assigned_to == session['user_id']:
            try:
                if 'status' in data:
                    task.status = data['status']
                
                if 'priority' in data and session['role'] == 'admin':
                    task.priority = data['priority']
                
                if 'deadline' in data and session['role'] == 'admin':
                    if data['deadline']:
                        try:
                            task.deadline = datetime.fromisoformat(data['deadline'])
                        except ValueError:
                            return jsonify({'success': False, 'message': 'Formato de data inválido'}), 400
                    else:
                        task.deadline = None
                
                if 'message' in data and data['message'].strip():
                    new_comment = TaskComment(
                        task_id=task.id,
                        user_id=session['user_id'],
                        message=data['message'].strip()
                    )
                    db.session.add(new_comment)
                
                if 'assigned_to' in data and session['role'] == 'admin':
                    task.assigned_to = data['assigned_to']
                
                db.session.commit()
                return jsonify({'success': True})
            
            except Exception as e:
                db.session.rollback()
                app.logger.error(f'Erro ao atualizar tarefa: {str(e)}')
                return jsonify({'success': False, 'message': 'Erro interno'}), 500
        
        return jsonify({'success': False, 'message': 'Acesso não autorizado'}), 403
    
    return jsonify({'success': False, 'message': 'Requisição inválida'}), 400


@app.route('/task/create', methods=['GET', 'POST'])
@login_required
def create_task():
    if request.method == 'POST':
        try:
            # Capturar dados do formulário
            title = request.form.get('title', '').strip()
            url = request.form.get('url', '').strip()
            priority = int(request.form.get('priority', 3))
            deadline_str = request.form.get('deadline', '')
            comments = request.form.get('comments', '').strip()

            # Validação básica
            if not title:
                flash('Título é obrigatório', 'danger')
                return redirect(url_for('create_task'))
            
            if url and not url.startswith(('http://', 'https://')):
                flash('URL inválida (deve começar com http:// ou https://)', 'danger')
                return redirect(url_for('create_task'))

            # Converter dados
            deadline = datetime.fromisoformat(deadline_str) if deadline_str else None
            
            # Definir responsável
            if session['role'] == 'admin':
                assigned_to = int(request.form.get('assigned_to', session['user_id']))
            else:
                assigned_to = session['user_id']

            # Criar nova tarefa
            new_task = Task(
                title=title,
                url=url if url else None,
                priority=priority,
                deadline=deadline,
                assigned_to=assigned_to
            )

            # Adicionar comentário inicial se existir
            if comments:
                new_comment = TaskComment(
                    message=comments,
                    user_id=session['user_id'],
                    task=new_task  # Usando o relacionamento
                )
                db.session.add(new_comment)

            db.session.add(new_task)
            db.session.commit()

            flash('Tarefa criada com sucesso!', 'success')
            return redirect(url_for('index'))

        except ValueError as e:
            db.session.rollback()
            flash(f'Erro de formato: {str(e)}', 'danger')
        except Exception as e:
            db.session.rollback()
            flash(f'Erro ao criar tarefa: {str(e)}', 'danger')
        
        return redirect(url_for('create_task'))

    # GET: Mostrar formulário
    users = User.query.all() if session.get('role') == 'admin' else []
    return render_template('create_task.html', users=users)

@app.route('/sync', methods=['POST'])
@login_required
def sync_tasks():
    if session['role'] != 'admin':
        return jsonify({'success': False, 'message': 'Não autorizado'}), 403
    
    total_synced = 0
    errors = []

    for api_url in app.config['SYNC_URLS']:
        try:
            response = requests.get(api_url, timeout=10)
            response.raise_for_status()
            external_tasks = response.json()
            
            # Converter para lista única se a API retornar objetos aninhados
            if isinstance(external_tasks, dict):
                external_tasks = external_tasks.get('items', [])

            synced = 0
            for task_data in external_tasks:
                try:
                    # Extração segura de dados
                    task_id = task_data.get('id')
                    
                    # Tratar o título que pode vir como dicionário
                    title = task_data.get('title')
                    if isinstance(title, dict):
                        title = title.get('rendered', 'Sem título')
                    elif not title:
                        title = 'Sem título'
                    
                    # Extrair URL
                    url = task_data.get('url') or task_data.get('link', '#')

                    # Ignorar itens sem ID ou título
                    if not task_id or not title:
                        continue

                    # Verificar se a tarefa já existe
                    if not Task.query.get(task_id):
                        new_task = Task(
                            id=task_id,
                            title=title,
                            url=url,
                            status='pending'
                        )
                        db.session.add(new_task)
                        synced += 1
                        
                except Exception as e:
                    errors.append(f"Erro no item {task_id} da {api_url}: {str(e)}")
                    db.session.rollback()  # Rollback para evitar problemas de transação
                    continue

            db.session.commit()
        except requests.exceptions.RequestException as e:
            errors.append(f"Falha na conexão com {api_url}: {str(e)}")
        except ValueError as e:
            errors.append(f"Resposta inválida de {api_url}: {str(e)}")
        except Exception as e:
            errors.append(f"Erro geral em {api_url}: {str(e)}")
            db.session.rollback()

    if errors:
        flash(f"Alguns erros ocorreram: {' | '.join(errors[:3])}", 'danger')
    if total_synced:
        flash(f"Total de tarefas sincronizadas: {total_synced}", 'info')
    else:
        flash("Nenhuma nova tarefa encontrada nas APIs", 'warning')

    return redirect(url_for('index'))

@app.route('/task/comments/<int:task_id>', methods=['GET'])
@login_required
def get_task_comments(task_id):
    task = Task.query.get_or_404(task_id)
    comments = [
        {
            'id': comment.id,
            'user': comment.user.username,
            'message': comment.message,
            'created_at': comment.created_at.strftime('%d/%m/%Y %H:%M')
        }
        for comment in task.comments
    ]
    return jsonify(comments)

@app.route('/task/delete/<int:task_id>', methods=['POST'])
@login_required
def delete_task(task_id):
    if session['role'] != 'admin':
        return jsonify({'success': False, 'message': 'Não autorizado'}), 403
    
    task = Task.query.get_or_404(task_id)
    task.is_active = False
    db.session.commit()
    return jsonify({'success': True})

# Initialize database
@app.cli.command('init-db')
def init_db_command():
    db.create_all()
    
    if not User.query.filter_by(username='admin').first():
        admin = User(username='admin', password='admin123', role='admin')
        db.session.add(admin)
        reviewer = User(username='reviewer', password='reviewer123', role='reviewer')
        db.session.add(reviewer)
        db.session.commit()

if __name__ == '__main__':
    app.run(debug=True)
