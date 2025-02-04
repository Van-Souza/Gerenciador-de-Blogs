import os
from app import app, db

def reset_database():
    # Caminho para o arquivo do banco de dados
    db_path = os.path.join(app.instance_path, 'tasks.db')
    
    # Verifica se o arquivo do banco de dados existe
    if os.path.exists(db_path):
        print(f"Banco de dados encontrado em: {db_path}")
        print("Apagando banco de dados existente...")
        os.remove(db_path)  # Remove o arquivo do banco de dados
        print("Banco de dados apagado com sucesso!")
    else:
        print("Nenhum banco de dados encontrado para apagar.")

    # Cria uma nova instância do banco de dados
    print("Criando novo banco de dados...")
    with app.app_context():
        db.create_all()  # Cria todas as tabelas definidas nos modelos
        print("Banco de dados criado com sucesso!")

        # Adiciona dados iniciais (opcional)
        print("Adicionando dados iniciais...")
        admin = User(username='admin', password='admin123', role='admin')
        reviewer = User(username='reviewer', password='reviewer123', role='reviewer')
        db.session.add(admin)
        db.session.add(reviewer)
        db.session.commit()
        print("Dados iniciais adicionados com sucesso!")

if __name__ == '__main__':
    reset_database()