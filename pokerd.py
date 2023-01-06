#!/usr/bin/env python3

''' pokerd.py - Simple Poker Server Daemon


'''

import asyncio
import collections
import dataclasses
import enum
import logging
import random

# Constants

POKERD_HOST     = '0.0.0.0'
POKERD_PORT     = 9204
POKERD_VERSION  = '0.0.1'

# Classes

class PokerState(enum.Enum):
    LOBBY = enum.auto()
    TABLE = enum.auto()

    HAND  = enum.auto()
    BETH  = enum.auto()
    FLOP  = enum.auto()
    BETF  = enum.auto()
    TURN  = enum.auto()
    BETT  = enum.auto()
    RIVER = enum.auto()
    BETR  = enum.auto()

    FOLD  = enum.auto()
    SCORE = enum.auto()
    QUIT  = enum.auto()


class PokerCard:
    HEARTS   = chr(9829) # Character 9829 is '♥'
    DIAMONDS = chr(9830) # Character 9830 is '♦'
    SPADES   = chr(9824) # Character 9824 is '♠'
    CLUBS    = chr(9827) # Character 9827 is '♣'
    RANK     = {
        11: 'J',
        12: 'Q',
        13: 'K',
        14: 'A',
    }

    def __init__(self, rank, suit):
        self.rank = rank
        self.suit = suit

    def __str__(self):
        return f'[{PokerCard.RANK.get(self.rank, self.rank):<2}{self.suit}]'


class PokerDeck:
    def __init__(self):
        self.shuffle()

    def shuffle(self):
        self.cards = []
        for suit in (PokerCard.HEARTS, PokerCard.DIAMONDS, PokerCard.SPADES, PokerCard.CLUBS):
            for rank in range(2, 15):
                self.cards.append(PokerCard(rank, suit))
        random.shuffle(self.cards)

    def deal(self):
        return self.cards.pop()


class PokerDealer:
    BANNER = f'''Welcome to Poker Daemon {POKERD_VERSION}
                 _                _
     _ __   ___ | | _____ _ __ __| |
    | '_ \ / _ \| |/ / _ \ '__/ _` |
    | |_) | (_) |   <  __/ | | (_| |
    | .__/ \___/|_|\_\___|_|  \__,_|
    |_|
    '''
    MINIMUM_PLAYERS = 2

    def __init__(self, host=POKERD_HOST, port=POKERD_PORT):
        self.host    = host
        self.port    = port
        self.state   = PokerState.LOBBY
        self.players = []
        self.deck    = PokerDeck()
        self.table   = []

    def add_player(self, player):
        self.players.append(player)
        logging.info('Now have %d players', len(self.players))

        if len(self.players) < PokerDealer.MINIMUM_PLAYERS:
            self.state = PokerState.TABLE
        else:
            self.state = PokerState.HAND
            for player in self.players:
                player.hand = []
            self.deck.shuffle()

    def remove_player(self, player):
        self.players.remove(player)
        logging.info('Now have %d players', len(self.players))
        if not self.players:
            self.state = PokerState.LOBBY

    def deal(self):
        return self.deck.deal()

    async def deal_hands(self):
        if self.state == PokerState.HAND:
            self.state = PokerState.FLOP
            for i in range(1, 3):
                for player in self.players:
                    player.hand.append(self.deal())

    async def deal_flop(self):
        if self.state == PokerState.FLOP:
            self.deal()
            self.state = PokerState.TURN
            self.table = [self.deal() for _ in range(3)]

    async def deal_turn(self):
        if self.state == PokerState.TURN:
            self.deal()
            self.state = PokerState.RIVER
            self.table.append(self.deal())

    async def deal_river(self):
        if self.state == PokerState.RIVER:
            self.deal()
            self.state = PokerState.SCORE
            self.table.append(self.deal())

    async def reset(self):
        if self.state != PokerState.LOBBY:
            self.state   = PokerState.LOBBY
            self.players = []

    async def run(self):
        self.server = await asyncio.start_server(
            PokerPlayer.make_client_handler(self),
            self.host,
            self.port
        )

        addresses = ', '.join(':'.join(map(str, s.getsockname())) for s in self.server.sockets)
        logging.info('Serving on %s', addresses)

        async with self.server:
            await self.server.serve_forever()


class PokerPlayer:

    def __init__(self, dealer, reader, writer):
        self.hand    = []
        self.dealer  = dealer
        self.reader  = reader
        self.writer  = writer
        self.state   = PokerState.LOBBY
        self.address = ':'.join(map(str, writer.get_extra_info('peername')))
        self.name    = f'Player {self.address}'
        self.wins    = 0

    # I/O Methods

    async def write_lines(self, lines, overwrite=False):
        for line in lines.split('\n'):
            prefix = '\r' if overwrite else '\n'
            self.writer.write(f'{prefix}{line}'.encode())
        await self.writer.drain()

    async def read_response(self, prompt):
        response = None
        while not response:
            await self.write_lines(f'\n{prompt}? ')
            response = (await self.reader.readline()).decode().strip().lower()
        return response

    # Player Methods

    async def display_banner(self):
        await self.write_lines(self.dealer.BANNER)

    async def wait_in_lobby(self):
        await self.write_lines('\nWaiting in lobby for next round...')

        seconds = 0
        while self.dealer.state not in (PokerState.LOBBY, PokerState.TABLE):
            seconds += 1
            await self.write_lines(f'Waiting in lobby for next round... {seconds}s', True)
            await asyncio.sleep(1)

        self.state = PokerState.TABLE

    async def wait_at_table(self):
        await self.write_lines('\nWaiting at table for players...')

        self.dealer.add_player(self)

        seconds = 0
        while self.dealer.state == PokerState.TABLE:
            seconds += 1
            await self.write_lines(f'Waiting at table for players... {seconds}s', True)
            await asyncio.sleep(1)

        self.state = PokerState.HAND

        while not all(player.state == PokerState.HAND for player in self.dealer.players):
            await asyncio.sleep(1)

        await self.write_lines(f'\nTable has {len(self.dealer.players)} players\n')
        for player in self.dealer.players:
            await self.write_lines(f'{player.name:>18}: {player.wins} wins')

    async def wait_for_hand(self):
        await self.write_lines('\nDealing hand...')
        await self.dealer.deal_hands()

        self.state = PokerState.BETH

        while not all(player.state == PokerState.BETH for player in self.dealer.players):
            await asyncio.sleep(1)

        await self.write_lines(f'\n        Your cards: {"".join(map(str, self.hand))}')

    async def wait_for_flop(self):
        await self.write_lines('\nDealing flop...')
        await self.dealer.deal_flop()

        self.state = PokerState.BETF

        while not all(player.state == PokerState.BETF for player in self.dealer.players):
            await asyncio.sleep(1)

        await self.write_lines(f'\n        Flop cards: {"".join(map(str, self.dealer.table))}')
        await self.write_lines(f'        Your cards: {"".join(map(str, self.hand))}')

    async def wait_for_turn(self):
        await self.write_lines('\nDealing turn...')
        await self.dealer.deal_turn()

        self.state = PokerState.BETT

        while not all(player.state == PokerState.BETT for player in self.dealer.players):
            await asyncio.sleep(1)

        await self.write_lines(f'\n        Turn cards: {"".join(map(str, self.dealer.table))}')
        await self.write_lines(f'        Your cards: {"".join(map(str, self.hand))}')

    async def wait_for_river(self):
        await self.write_lines('\nDealing river...')
        await self.dealer.deal_river()

        self.state = PokerState.BETR

        while not all(player.state == PokerState.BETR for player in self.dealer.players):
            await asyncio.sleep(1)

        await self.write_lines(f'\n       River cards: {"".join(map(str, self.dealer.table))}')
        await self.write_lines(f'        Your cards: {"".join(map(str, self.hand))}')

    async def wait_for_call(self, next_state):
        response = await self.read_response('Choose an action: (F)old or (C)all')

        if response == 'f':
            self.state = PokerState.FOLD
            self.dealer.remove_player(self)
            await self.write_lines('\nYou lost...')
        else:
            self.state = next_state

            await self.write_lines('Waiting for other players...')
            seconds = 0
            while not all(player.state == next_state for player in self.dealer.players):
                await self.write_lines(f'Waiting for other players... {seconds}s', True)
                await asyncio.sleep(1)
                seconds += 1

            if len(self.dealer.players) == 1:
                self.state = PokerState.SCORE

    async def score_hands(self):
        await self.write_lines(f'\n       Table cards: {"".join(map(str, self.dealer.table))}')
        winner_score = 0
        for player in self.dealer.players:
            player_score = score_hand(player.hand, self.dealer.table)
            winner_score = max(winner_score, player_score)
            await self.write_lines(
                f'{player.name:>10}\'s cards: {"".join(map(str, player.hand))} (Score: {player_score})'
            )

        if winner_score == score_hand(self.hand, self.dealer.table):
            self.wins += 1
            await self.write_lines('\nYou are the winner!')
        else:
            await self.write_lines('\nYou lost...')

        await self.write_lines('\nWaiting for other players...')
        self.state = PokerState.LOBBY
        seconds    = 0
        while not all(player.state == PokerState.LOBBY for player in self.dealer.players):
            await self.write_lines(f'Waiting for other players... {seconds}s', True)
            await asyncio.sleep(1)
            seconds += 1

        await self.dealer.reset()

    # Static Methods

    @staticmethod
    async def handle_client(dealer, reader, writer):
        player = PokerPlayer(dealer, reader, writer)
        logging.info('Player %s connected!', player.address)

        await player.display_banner()

        player.name = await player.read_response('What is your name')

        try:
            while player.state != PokerState.QUIT:
                if   player.state == PokerState.LOBBY: await player.wait_in_lobby()
                elif player.state == PokerState.TABLE: await player.wait_at_table()
                elif player.state == PokerState.HAND:  await player.wait_for_hand()
                elif player.state == PokerState.BETH:  await player.wait_for_call(PokerState.FLOP)
                elif player.state == PokerState.FLOP:  await player.wait_for_flop()
                elif player.state == PokerState.BETF:  await player.wait_for_call(PokerState.TURN)
                elif player.state == PokerState.TURN:  await player.wait_for_turn()
                elif player.state == PokerState.BETT:  await player.wait_for_call(PokerState.RIVER)
                elif player.state == PokerState.RIVER: await player.wait_for_river()
                elif player.state == PokerState.BETR:  await player.wait_for_call(PokerState.SCORE)
                elif player.state == PokerState.SCORE: await player.score_hands()
                elif player.state == PokerState.FOLD:  player.state = PokerState.LOBBY

                await asyncio.sleep(1)
        except ConnectionResetError:
            pass
        finally:
            player.dealer.remove_player(player)

    @staticmethod
    def make_client_handler(dealer):
        return lambda writer, reader: PokerPlayer.handle_client(dealer, writer, reader)


# Functions

def score_hand(hand, table):
    # 10. High Card (2-14)
    ranks = sorted(c.rank for c in hand)
    suits = [c.suit for c in hand]
    score = ranks[-1]

    # 9, 8, 7, 4, 3. Pair, Two Pair, Three of a Kind, Full House, Four of a Kind
    rank_counts  = collections.Counter(c.rank for c in hand + table)
    pair_counts  = 0
    three_counts = 0
    for rank, count in sorted(rank_counts.items()):
        if rank in ranks:           # Note: disregard combos from only the table
            if count == 2:
                if not pair_counts:                     # Pair:             20 - 34
                    score = 20 + rank
                else:                                   # Two Pair:         42 - 54
                    score = 40 + rank
                pair_counts += 1
            elif count == 3:
                if not pair_counts and not three_counts:# Three of kind:    62 - 74
                    score = 60 + rank
                else:                                   # Full house:       120 - 134
                    score = 120 + rank
                three_counts += 1
            elif count == 4:                            # Four of a kind:   140 - 154
                score = 140 + rank

    # 6. Straight
    all_ranks = sorted(c.rank for c in hand + table)
    for base in range(0, len(all_ranks) - 4):           # Straight: 80 - 94
        straight = True
        in_ranks = all_ranks[base] in ranks
        for index in range(1, 5):
            in_ranks |= all_ranks[base + index] in ranks
            if all_ranks[base + index] - all_ranks[base + index - 1] > 1:
                straight = False

        if straight and in_ranks:
            score = 80 + all_ranks[base + 4]

    # 5. Flush
    suit_counts = collections.Counter(c.suit for c in hand + table)
    for suit, count in suit_counts.items():             # Flush: 100 - 114
        if suit in suits and count >= 5:
            score = 100

    # TODO: straight flush, royal flush
    return score

# Main Execution

async def main():
    logging.basicConfig(
        format   = '[%(levelname)1.1s %(asctime)s %(module)s:%(lineno)d] %(message)s',
        datefmt  = '%Y-%m-%d %H:%M:%S',
        level    = logging.INFO,
    )

    dealer = PokerDealer()
    await dealer.run()

if __name__ == '__main__':
    asyncio.run(main())
