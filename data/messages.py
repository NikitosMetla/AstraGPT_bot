async def start_message(language: str):
    if language == "en":
        return ("Greetings to you! Here you can chat with an AI assistant, "
                 "who will be able to guide you on any issue related to the event\n\n "
                 "Just write any message and the assistant will answer it for you",
                 "Choose a language for communication")
    elif language == "kz":
        return ("Сізді құттықтаймыз! Мұнда сіз AI көмекшісімен сөйлесе аласыз, "
                "сізді\n\n оқиғасына қатысты кез келген мәселе бойынша бағыттай алады"
                "Тек кез-келген хабарлама жазыңыз, сонда көмекші сізге жауап береді",
                "Қарым-қатынас үшін Тілді таңдаңыз")
    else:
        return ("Приветствуем тебя! Здесь ты можешь пообщаться с AI ассистентом, "
                "который сможет сориентировать тебя по любому вопросу, связанным с мероприятием\n\n "
                "Просто напиши любое сообщение и ассистент ответит тебе на него",
                "Выбери язык для общения")


async def update_language(language: str) -> str:
    # full_language = "Русский" if language == "ru" else "Қазақша" if language == "kz" else "English" if language == "en" else "None"
    if language == "ru":
        text = ("Отлично, вы выбрали Русский язык. Теперь вы можете общаться с ассистентом на выбранном языке."
                " \n\nЧтобы еще раз поменять язык введите команду /start")
    elif language == "kz":
        text = (f"Өте жақсы, сіз орыс Қазақша таңдадыңыз. Енді сіз ассистентпен таңдалған тілде сөйлесе аласыз. \n\n"
                "птілін тағы бір рет өзгерту үшін /start пәрменін теріңіз")
    else:
        text = ("Great, you've chosen English. Now you can communicate with the assistant in the selected language."
                " \n\n To change the language again, enter the command /start")
    return text


async def wait_manager(language: str) -> str:
    if language == "ru":
        text = ("Если вам нужна помощь менеджера, пожалуйста, позвоните в наш колл-центр по телефону:"
                " +77077094444 \n\nБудем рады помочь! 😊")
    elif language == "kz":
        text = ("Егер сізге менеджердің көмегі қажет болса, біздің колл-орталыққа келесі нөмір бойынша қоңырау шалыңыз:"
                " +77077094444 \n\nБіз сізге көмектесуге әрқашан дайынбыз! 😊")
    else:
        text = ("If you need assistance from a manager, please call our call center at:"
                " +77077094444 \n\nWe will be happy to help! 😊")
    return text