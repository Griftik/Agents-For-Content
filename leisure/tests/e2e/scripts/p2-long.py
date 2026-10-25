"""Добавить/удалить тестовое событие с очень длинным названием: python -I p2-long.py add|del"""
import sys, uuid
sys.path.insert(0, '/home/user/Agents-For-Content')
from sqlalchemy import select
from leisure.db import models
from leisure.db.session import session_factory
SLUG = 'qa-long-title-event'
with session_factory()() as s:
    ev = s.execute(select(models.Event).where(models.Event.slug == SLUG)).scalar_one_or_none()
    if sys.argv[1] == 'del':
        if ev: s.delete(ev); s.commit()
        print('deleted', bool(ev)); sys.exit()
    src = s.execute(select(models.Event).where(models.Event.slug == 'vakhtangov-faust-timoshenko')).scalar_one()
    if ev is None:
        ev = models.Event(**{c.name: getattr(src, c.name) for c in models.Event.__table__.columns if c.name not in ('id', 'created_at', 'updated_at')})
        ev.id = uuid.uuid4(); s.add(ev)
    ev.slug = SLUG
    ev.title = ('Сверхдлинное название ' * 6) + ('А' * 102) + ' и ещё хвост ' + ('Б' * 30) + ' конец названия события для проверки переноса на узком экране'
    ev.venue = 'Государственный' + 'В' * 70 + 'ыйтеатр'
    ev.start_time = None if False else ev.start_time
    s.commit(); print('added', len(ev.title))
