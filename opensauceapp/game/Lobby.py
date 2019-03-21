import random
import datetime
from threading import Thread
from time import sleep
import json
import string
import unidecode
from asgiref.sync import async_to_sync

from ..models import Sauce
from ..models import SauceCategory

from .Player import Player


class Lobby:
    # States
    WAITING_FOR_PLAYERS = 0
    GAME_START_SOON = 1
    QUESTION = 2
    ANSWER = 3
    GAME_END = 4

    timeoutWhenGameStarting = datetime.timedelta(seconds=1)
    timeoutWhenQuestion = datetime.timedelta(seconds=4)
    timeoutWhenAnswer = datetime.timedelta(seconds=4)
    timeoutWhenGameFinished = datetime.timedelta(seconds=3)

    score_goals = [10, 20, 30, 50, 100, 200]
    default_score_goal = 20

    ignored_prefix_char_sequence = ["the", "a", "an", "le", "la", "les"]

    min_players = 1
    max_round_without_points = 10

    # the last is repeated for all the next players
    points_repartition = [5, 3, 2, 1]

    def __init__(self, name):
        self.name = name
        self.players = {}
        self.settings = self.default_settings()
        self.reset()

    def reset(self):
        """Reset the lobby to a basic state"""
        self.state = Lobby.WAITING_FOR_PLAYERS
        self.state_id = random.randrange(0, 999999)
        self.round_without_points = 0
        self.current_sauce = None
        self.datetime = datetime.datetime.now()
        self.player_that_found = []
        for player in self.players.values():
            player.reset_game()
        self.history = []
        self.sauces = self.fetch_sauces_from_settings()
        self.update_and_send_state(True)

    @staticmethod
    def default_settings():
        """Everything is enabled by default"""
        settings = {}
        settings["categories"] = []
        settings["score_goal_value"] = Lobby.default_score_goal
        categories = SauceCategory.objects.all()
        for category in categories:
            for difficulty in range(1, 4): # 1-3
                setting = {'category_id': category.id, 'difficulty': difficulty, 'value': True}
                settings["categories"].append(setting)
        return settings

    def fetch_sauces_from_settings(self):
        all_sauces = Sauce.objects.all()
        filtred_sauces = []

        settings_lookup = {}
        # print(self.settings)
        for category in self.settings["categories"]:
            category_id = category["category_id"]
            difficulty = category["difficulty"]
            value = category["value"]
            settings_lookup[(category_id, difficulty)] = value

        # it's difficult with filter so we do it manualy
        for sauce in all_sauces:
            if settings_lookup[(sauce.sauce_category.id, sauce.difficulty)]:
                filtred_sauces.append(sauce)

        return filtred_sauces

    def count(self):
        return len(self.players)

    def get_players(self):
        return list(filter(lambda p: p.isPlaying, self.players.values()))

    def get_spectators(self):
        return list(filter(lambda p: not p.isPlaying, self.players.values()))

    def count_players(self):
        return len(self.get_players())

    def count_spectators(self):
        return len(self.get_spectators())

    def update_and_send_state(self, restart = False):
        self.update_state(restart)
        self.send_current_state()

    def game_start_soon_delay(self):
        self.datetime = datetime.datetime.now() + Lobby.timeoutWhenGameStarting
        sleep(Lobby.timeoutWhenGameStarting.total_seconds())
        if Lobby.GAME_START_SOON == self.state:
            self.next_round()
            self.send_question()

    def set_settings(self, settings):
        self.settings = settings
        self.sauces = self.fetch_sauces_from_settings()
        # for i in self.sauces:
        #     print(i)
        self.send_settings()

    def question_delay(self, state_id):
        self.datetime = datetime.datetime.now() + Lobby.timeoutWhenQuestion
        sleep(Lobby.timeoutWhenQuestion.total_seconds())
        # no more time (not everybody found), check the state id in case of everybody found the answer
        if Lobby.QUESTION == self.state and state_id == self.state_id:
            self.answer()

    def answer(self):
        # reset the room use to prevent people from staying without playing
        if len(self.player_that_found) <= 0:
            self.round_without_points += 1
            if self.round_without_points >= Lobby.max_round_without_points:
                self.reset()
        self.history.append((self.current_sauce, self.player_that_found))
        self.send_answer()
        thread = Thread(target=self.answer_delay)
        thread.start()

    def get_best_player(self):
        playerSorted = sorted(self.get_players(), key=lambda p: p.score)
        if len(playerSorted) <= 0:
            return False
        else:
            return playerSorted[0]

    def answer_delay(self):
        self.datetime = datetime.datetime.now() + Lobby.timeoutWhenAnswer
        sleep(Lobby.timeoutWhenAnswer.total_seconds())
        if Lobby.ANSWER == self.state:
            best_player = self.get_best_player()
            if best_player and best_player.score + best_player.points_this_round >= self.settings["score_goal_value"]:
                self.send_game_end()
                sleep(Lobby.timeoutWhenGameFinished.total_seconds())
                self.reset()
            else:
                self.next_round()
                self.send_question()

    def next_round(self):
        # reset players
        for player in self.players.values():
            player.reset_round()
        self.send_scoreboard()
        # set new sauce
        self.current_sauce = random.choice(self.sauces)
        self.state_id = random.randrange(0, 999999)
        # reset play that found
        self.player_that_found = []
        # set new end time
        thread = Thread(target=self.question_delay,
                        args=(self.state_id,))
        thread.start()

    def update_state(self, restart):
        if not restart and self.count_players() <= 0:
            self.reset()

        if Lobby.WAITING_FOR_PLAYERS == self.state:
            if self.count_players() >= Lobby.min_players:
                self.state = Lobby.GAME_START_SOON
                thread = Thread(target=self.game_start_soon_delay)
                thread.start()
        elif Lobby.GAME_START_SOON == self.state:
            pass
        elif Lobby.QUESTION == self.state:
            if len(self.player_that_found) >= self.count_players():
                self.state = Lobby.ANSWER
                self.datetime = datetime.datetime.now() + Lobby.timeoutWhenQuestion
        elif Lobby.ANSWER == self.state:
            pass
        elif Lobby.GAME_END == self.state:
            pass
        else:
            raise "Unhandled state"

    def send_current_state(self):
        self.send_scoreboard()
        self.send_settings()
        if Lobby.WAITING_FOR_PLAYERS == self.state:
            self.send_waiting_for_players()
        elif Lobby.GAME_START_SOON == self.state:
            self.send_game_starts_soon()
        elif self.state == Lobby.QUESTION:
            self.send_question()
        elif Lobby.ANSWER == self.state:
            self.send_answer()
        elif Lobby.GAME_END == self.state:
            self.send_game_end()
        else:
            raise "Unhandled state"

    def player_add(self, secKey, socket):
        player = Player(socket)
        if len(self.players) < 1:
            player.isOwner = True
        self.players[secKey] = player
        self.send_scoreboard()
        self.update_and_send_state()

    def player_remove(self, secKey):
        if secKey in self.players:
            del self.players[secKey]
        # if the last player is remove the lobby tell to remove the lobby
        self.update_and_send_state()
        return self.count() <= 0

    def player_join(self, secKey, playerName):
        player = self.players[secKey]
        player.isPlaying = True
        player.set_name(playerName)
        self.update_and_send_state()

    def player_leave(self, secKey):
        player = self.players[secKey]
        player.reset_game()
        if self.count_players() <= 0:
            self.reset()
        else:
            self.send_scoreboard()

    def add_player_points(self, player):
        index = len(self.player_that_found)
        len_points_repartition_MinusOne = len(Lobby.points_repartition) - 1
        if index >= len_points_repartition_MinusOne:
            index = len_points_repartition_MinusOne

        self.player_that_found.append(player)
        player.add_points(Lobby.points_repartition[index])

    def player_submit(self, secKey, answer):
        # Can submit now...
        if Lobby.QUESTION != self.state:
            return
        player = self.players[secKey]
        if not player.isPlaying:
            return
        if not player.can_earn_points():
            return

        if Lobby.sanitize(answer) == Lobby.sanitize(self.current_sauce.answer):
            # correct answer
            self.add_player_points(player)
            if len(self.player_that_found) >= self.count_players():
                self.answer()
            self.send_scoreboard()

    @staticmethod
    def sanitize(s):
        # any special char unicode char to the closest ascci char
        s = unidecode.unidecode(s)
        # remove punctuation and remove whitespaces
        s = s.translate(str.maketrans('', '', string.punctuation))
        # only lower cases
        s = s.lower()
        # remove special char sequence
        for sequence in Lobby.ignored_prefix_char_sequence:
            l = len(sequence)
            word_prefix = s[:l]
            if word_prefix == sequence:
                s = s[l:]
                break
        s = s.translate(str.maketrans('', '', string.whitespace))
        return s

    def __str__(self):
        s = "--" + self.name + ", status : " + str(self.state) + "\n"
        for name, player in self.players.items():
            s += "---- " + str(name) + " : " + str(player) + "\n"
        return s

    def send_settings(self):
        settings = {}
        settings["settings"] = self.settings
        settings["datetime"] = self.datetime.timestamp()
        data = {"type": "settings", "data": settings}
        self.broadcast(data)

    def send_scoreboard(self):
        # Players and spectators
        players = []
        spectators = []
        for player in self.players.values():
            player_status = player.get_status()
            if player.isPlaying:
                players.append(player_status)
            else:
                spectators.append(player_status)

        scoreboard = {}
        # sorted by score
        scoreboard["players"] = list(
            sorted(players, key=lambda x: -x["score"]))
        # sorted by name
        scoreboard["spectators"] = list(
            sorted(spectators, key=lambda x: x["name"]))

        # Handle history
        scoreboard["history"] = []
        for sauce, players_history in self.history[::-1]:
            if sauce is None:
                continue
            d = {}
            d["id"] = sauce.id
            d["answer"] = sauce.answer
            d["players"] = []
            for p in players_history:
                d["players"].append(p.name)
            scoreboard["history"].append(d)

        scoreboard["datetime"] = self.datetime.timestamp()

        # print("send scoreboard", scoreboard)
        data = {"type": "scoreboard", "data": scoreboard}
        self.broadcast(data)

    def send_waiting_for_players(self):
        self.state = Lobby.WAITING_FOR_PLAYERS
        waiting_for_players = {}
        waiting_for_players["qte"] = Lobby.min_players - self.count_players()
        waiting_for_players["datetime"] = self.datetime.timestamp()
        # print("send waiting for players : ", waiting_for_players)
        self.broadcast(
            {"type": "waiting_for_players", "data": waiting_for_players})

    def send_game_starts_soon(self):
        self.state = Lobby.GAME_START_SOON
        game_starts_soon = {}
        game_starts_soon["datetime"] = self.datetime.timestamp()
        # print("send game starts soon : ", game_starts_soon)
        self.broadcast(
            {"type": "game_starts_soon", "data": game_starts_soon})

    def send_question(self):
        self.state = Lobby.QUESTION
        question = {}
        question["question"] = self.current_sauce.question
        question["media_type"] = self.current_sauce.media_type
        question["category"] = self.current_sauce.sauce_category.name
        question["datetime"] = self.datetime.timestamp()
        # print("send question : ", question)
        self.broadcast({"type": "question", "data": question})

    def send_answer(self):
        if self.state is not Lobby.QUESTION:
            return
        self.state = Lobby.ANSWER
        answer = {}
        answer["answer"] = self.current_sauce.answer
        answer["datetime"] = self.datetime.timestamp()
        # print("send answer : ", answer)
        data = {"type": "answer", "data": answer}
        self.broadcast(data)

    def send_game_end(self):
        self.state = Lobby.GAME_END
        game_end = {}

        game_end["datetime"] = self.datetime.timestamp()
        game_end["winner"] = self.get_best_player().name

        # print("send game end : ", game_end)
        self.broadcast({"type": "game_end", "data": game_end})

    def broadcast(self, data):
        jsondumps = json.dumps(data)
        for player in self.players.values():
            player.socket.send(text_data=jsondumps)
