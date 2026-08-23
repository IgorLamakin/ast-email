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
        # Проверяем каждое название по отдельности; если шаблон уже есть —
        # ОБНОВЛЯЕМ его html_content (новые версии писем должны дойти до тех,
        # кто уже пользуется стандартными шаблонами), вместо пропуска.
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
            filepath = os.path.join(template_dir, filename)
            if not os.path.exists(filepath):
                print(f"Warning: {filepath} not found, skipping.")
                continue
            with open(filepath, "r", encoding="utf-8") as f:
                html = f.read()

            existing = db.query(models.Template).filter(models.Template.title == title).first()
            if existing:
                if existing.html_content != html:
                    existing.html_content = html
                    # updated_at обновится автоматически (onupdate в models.Template)
                    db.add(existing)
                    added_any = True
                    print(f"Updated template: {title}")
                else:
                    print(f"Already up to date: {title}")
            else:
                # на случай, если шаблон удалили — восстанавливаем у владельца (admin)
                admin = db.query(models.User).filter(models.User.role == models.UserRole.ADMIN).first()
                if not admin:
                    print("No admin user found. Please register an admin user first.")
                    continue
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
            print("Nothing to change - all templates already up to date.")
    finally:
        db.close()

if __name__ == "__main__":
    seed()
