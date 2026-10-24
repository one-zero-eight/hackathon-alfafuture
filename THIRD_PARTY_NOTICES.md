## List of outsource news agents RSS used:

1. Lenta.ru

Main: https://lenta.ru/rss

    Новости (все): https://lenta.ru/rss/news
    Новости / Россия: https://lenta.ru/rss/news/russia
    Новости / Мир: https://lenta.ru/rss/news/world
    Новости / Экономика: https://lenta.ru/rss/news/economy
    Новости / Наука: https://lenta.ru/rss/news/science
    Новости / Спорт: https://lenta.ru/rss/news/sport
    Новости / Культура: https://lenta.ru/rss/news/culture
    Новости / Медиа: https://lenta.ru/rss/news/media
    Новости / Фото: https://lenta.ru/rss/news/photo
    Новости / Колонки: https://lenta.ru/rss/news/columns
    Статьи: https://lenta.ru/rss/articles
    Колонки: https://lenta.ru/rss/columns
    Топ-7: https://lenta.ru/rss/top7
    Фото: https://lenta.ru/rss/photo

2. Известия (iz.ru)

Main: https://iz.ru/xml/rss/all.xml

    Политика: https://iz.ru/xml/rss/politics.xml
    Экономика: https://iz.ru/xml/rss/economy.xml
    Общество: https://iz.ru/xml/rss/society.xml
    Происшествия: https://iz.ru/xml/rss/accidents.xml
    В мире: https://iz.ru/xml/rss/world.xml
    Спорт: https://iz.ru/xml/rss/sport.xml
    Культура: https://iz.ru/xml/rss/culture.xml
    Наука: https://iz.ru/xml/rss/science.xml
    Технологии: https://iz.ru/xml/rss/technologies.xml
    Промышленность: https://iz.ru/xml/rss/industry.xml
    Армия: https://iz.ru/xml/rss/army.xml
    Мнения: https://iz.ru/xml/rss/opinions.xml
    Образование: https://iz.ru/xml/rss/education.xml
    Туризм: https://iz.ru/xml/rss/tourism.xml
    Недвижимость: https://iz.ru/xml/rss/realty.xml
    Медиа: https://iz.ru/xml/rss/media.xml

3. РИА Новости (ria.ru)

Main: https://ria.ru/export/rss2/archive/index.xml

    Спорт (sport.ria.ru): https://sport.ria.ru/export/rss2/archive/index.xml
    Туризм (tourism.ria.ru): https://tourism.ria.ru/export/rss2/archive/index.xml

> Примечание: у РИА тематические RSS (`/export/rss2/politics/`, `/export/rss2/economy/` и т.д.) больше не отдаются — отвечают 404/403. Доступны только основная лента и поддомены sport/tourism. Для рубрикации новостей РИА фильтруйте основную ленту по категориям в самих item. ---
Прочие проверенные источники (без раскрытия рубрик)
4. Интерфакс

Main: https://www.interfax.ru/rss.asp
5. ТАСС

Main: https://tass.ru/rss/v2.xml
6. Ведомости

    Новости (main): https://www.vedomosti.ru/rss/news
    Статьи: https://www.vedomosti.ru/rss/articles

7. Коммерсантъ

Main: https://www.kommersant.ru/RSS/news.xml
8. RT на русском

Main: https://russian.rt.com/rss
9. NEWS.ru

Main: https://news.ru/rss/
10. Взгляд

Main: https://vz.ru/rss.xml
11. REGNUM

Main: https://regnum.ru/rss/
12. Российская газета

Main: https://rg.ru/xml/index.xml
13. Sputnik

Main: https://sputniknews.com/export/rss2/archive/index.xml
14. Банки.ру

Main: https://www.banki.ru/xml/news.rss
15. N+1 (наука)

Main: https://nplus1.ru/rss
16. Хабр (технологии)

Main: https://habr.com/ru/rss/best/daily/
17. 3DNews (технологии)

Main: https://3dnews.ru/news/rss/

## Разбор для компании

Локально, не через шлюз организатора:

- `BAAI/bge-m3` — поиск ближайшего тезиса банка по заголовку новости. Лицензия MIT.
- `sentence-transformers` 6.2.0 — загрузка этой модели. Лицензия Apache-2.0.
- `torch` — вычисления для той же модели, ставится вместе с sentence-transformers.

Генерация текста идёт только через модели из списка организатора. Готовые агентные каркасы не используются.