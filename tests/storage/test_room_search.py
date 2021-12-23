# Copyright 2021 The Matrix.org Foundation C.I.C.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from unittest.case import SkipTest
from unittest.mock import PropertyMock, patch
import synapse.rest.admin
from synapse.rest.client import login, room
from synapse.storage.engines import PostgresEngine

from tests.unittest import HomeserverTestCase


class NullByteInsertionTest(HomeserverTestCase):
    servlets = [
        synapse.rest.admin.register_servlets_for_client_rest_resource,
        login.register_servlets,
        room.register_servlets,
    ]

    def test_null_byte(self):
        """
        Postgres/SQLite don't like null bytes going into the search tables. Internally
        we replace those with a space.

        Ensure this doesn't break anything.
        """

        # Register a user and create a room, create some messages
        self.register_user("alice", "password")
        access_token = self.login("alice", "password")
        room_id = self.helper.create_room_as("alice", tok=access_token)

        # Send messages and ensure they don't cause an internal server
        # error
        for body in ["hi\u0000bob", "another message", "hi alice"]:
            response = self.helper.send(room_id, body, tok=access_token)
            self.assertIn("event_id", response)

        # Check that search works for the message where the null byte was replaced
        store = self.hs.get_datastore()
        result = self.get_success(
            store.search_msgs([room_id], "hi bob", ["content.body"])
        )
        self.assertEquals(result.get("count"), 1)
        if isinstance(store.database_engine, PostgresEngine):
            self.assertIn("hi", result.get("highlights"))
            self.assertIn("bob", result.get("highlights"))

        # Check that search works for an unrelated message
        result = self.get_success(
            store.search_msgs([room_id], "another", ["content.body"])
        )
        self.assertEquals(result.get("count"), 1)
        if isinstance(store.database_engine, PostgresEngine):
            self.assertIn("another", result.get("highlights"))

        # Check that search works for a search term that overlaps with the message
        # containing a null byte and an unrelated message.
        result = self.get_success(store.search_msgs([room_id], "hi", ["content.body"]))
        self.assertEquals(result.get("count"), 2)
        result = self.get_success(
            store.search_msgs([room_id], "hi alice", ["content.body"])
        )
        if isinstance(store.database_engine, PostgresEngine):
            self.assertIn("alice", result.get("highlights"))


class PostgresMessageSearchTest(HomeserverTestCase):
    servlets = [
        synapse.rest.admin.register_servlets_for_client_rest_resource,
        login.register_servlets,
        room.register_servlets,
    ]

    def test_web_search_for_phrase(self):
        """
        Test searching for phrases using typical web search syntax, as per postgres' websearch_to_tsquery. 
        This test is skipped unless the postgres instance supports websearch_to_tsquery.
        """

        store = self.hs.get_datastore()
        if not isinstance(store.database_engine, PostgresEngine):
            raise SkipTest("Test only applies when postgres is used as the database")
        
        if not store.database_engine.supports_websearch_to_tsquery:
            raise SkipTest("Test only applies when postgres supporting websearch_to_tsquery is used as the database")

        phrase = "the quick brown fox jumps over the lazy dog"
        cases = [
            ("brown", True),
            ("quick brown", True),            
            ("brown quick", True),
            ("\"brown quick\"", False),
            ("\"quick brown\"", True),
            ("\"quick fox\"", False),
            ("furphy OR fox", True),
            ("nope OR doublenope", False),
            ("-fox", False),
            ("-nope", True),
        ]

        # Register a user and create a room, create some messages
        self.register_user("alice", "password")
        access_token = self.login("alice", "password")
        room_id = self.helper.create_room_as("alice", tok=access_token)
                
        # Send the phrase as a message and check it was created
        response = self.helper.send(room_id, phrase, tok=access_token)
        self.assertIn("event_id", response)
        
        # Run all the test cases        
        for query, has_results in cases:
            result = self.get_success(store.search_msgs([room_id], query, ["content.body"]))            
            self.assertEquals(result.get("count"), 1 if has_results else 0, query)

    def test_non_web_search_for_phrase(self):
        """
        Test searching for phrases without using web search, which is used when websearch_to_tsquery isn't 
        supported by the current postgres version. 
        """
        
        store = self.hs.get_datastore()
        if not isinstance(store.database_engine, PostgresEngine):
            raise SkipTest("Test only applies when postgres is used as the database")
    
        phrase = "the quick brown fox jumps over the lazy dog"
        cases = [
            ("nope", False),
            ("brown", True),
            ("quick brown", True),
            ("brown quick", True),
            ("brown nope", False),
            ("furphy OR fox", False), # syntax not supported
            ("\"quick brown\"", True), # syntax not supported, but strips quotes
            ("-nope", False), # syntax not supported
        ]

        # Register a user and create a room, create some messages
        self.register_user("alice", "password")
        access_token = self.login("alice", "password")
        room_id = self.helper.create_room_as("alice", tok=access_token)
                
        # Send the phrase as a message and check it was created
        response = self.helper.send(room_id, phrase, tok=access_token)
        self.assertIn("event_id", response)
                
        # Patch supports_websearch_to_tsquery to always return False to ensure we're testing the plainto_tsquery path.
        with patch("synapse.storage.engines.postgres.PostgresEngine.supports_websearch_to_tsquery", 
                    new_callable=PropertyMock) as supports_websearch_to_tsquery:
            supports_websearch_to_tsquery.return_value = False

            # Run all the test cases        
            for query, has_results in cases:
                result = self.get_success(store.search_msgs([room_id], query, ["content.body"]))                
                self.assertEquals(result.get("count"), 1 if has_results else 0, query)

class PostgresRoomSearchTest(HomeserverTestCase):
    # Register a user and create a room
    self.register_user("alice", "password")
    access_token = self.login("alice", "password")
    room_id = self.helper.create_room_as("alice", tok=access_token