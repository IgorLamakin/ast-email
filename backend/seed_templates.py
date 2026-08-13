import os
import sys

# Add backend dir to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database import SessionLocal, engine
import models

models.Base.metadata.create_all(bind=engine)

def seed():
    db = SessionLocal()
    try:
        # Проверяем каждое название по отдельности, а не только общее количество -
        # иначе при частичном наличии шаблонов (например, один удалили вручную)
        # скрипт добавил бы дубликаты остальных.
        existing_titles = {
            t.title for t in db.query(models.Template)
            .filter(models.Template.status == models.TemplateStatus.PUBLISHED).all()
        }

        # Find or create admin user
        admin = db.query(models.User).filter(models.User.role == models.UserRole.ADMIN).first()
        if not admin:
            print("No admin user found. Please register an admin user first.")
            return

        template_dir = os.path.join(os.path.dirname(__file__), "email_templates")
        templates = [
            ("АСТ — Общий обзор компании", "template_1_general.html"),
            ("АСТ — Поставка компонентов КИПиА и АСУТП", "template_2_supplies.html"),
            ("АСТ — Производство и сборка шкафов", "template_3_cabinets.html"),
            ("АСТ — Инжиниринг и разработка ПО", "template_4_engineering.html"),
            ("АСТ — Реализованные проекты", "template_5_cases.html"),
        ]

        added_any = False
        for title, filename in templates:
            if title in existing_titles:
                print(f"Already exists, skipping: {title}")
                continue
            filepath = os.path.join(template_dir, filename)
            if not os.path.exists(filepath):
                print(f"Warning: {filepath} not found, skipping.")
                continue
            with open(filepath, "r", encoding="utf-8") as f:
                html = f.read()
            t = models.Template(
                title=title,
                html_content=html,
                status=models.TemplateStatus.PUBLISHED,
                owner_id=admin.id
            )
            db.add(t)
            added_any = True
            print(f"Added template: {title}")

        if added_any:
            db.commit()
            print("Seed complete!")
        else:
            print("Nothing to add - all templates already exist.")
    finally:
        db.close()

if __name__ == "__main__":
    seed()
