import datetime
import unittest
from unittest.mock import AsyncMock, MagicMock

import bot
import seasonal


UTC = datetime.timezone.utc


def at(year, month, day, hour=0, minute=0):
    return datetime.datetime(year, month, day, hour, minute, tzinfo=UTC)


class TestCalendar(unittest.TestCase):
    def test_all_four_seasons_are_listed(self):
        for season in ("Spring", "Summer", "Autumn", "Winter"):
            self.assertTrue(
                any(sale.name.startswith(season) for sale in seasonal.SALES), season
            )

    def test_each_sale_ends_after_it_starts(self):
        for sale in seasonal.SALES:
            self.assertLess(sale.start, sale.end, sale.name)

    def test_sales_do_not_overlap(self):
        ordered = sorted(seasonal.SALES, key=lambda sale: sale.start)
        for earlier, later in zip(ordered, ordered[1:]):
            self.assertLessEqual(earlier.end, later.start, earlier.name)

    def test_sales_start_at_10_am_pacific_through_daylight_saving(self):
        winter = next(s for s in seasonal.SALES if s.name == "Winter Sale 2026")
        summer = next(s for s in seasonal.SALES if s.name == "Summer Sale 2027")
        self.assertEqual(winter.start.astimezone(UTC), at(2026, 12, 17, 18))
        self.assertEqual(summer.start.astimezone(UTC), at(2027, 6, 24, 17))

    def test_winter_sale_runs_into_the_new_year(self):
        winter = next(s for s in seasonal.SALES if s.name == "Winter Sale 2026")
        self.assertEqual(winter.end.year, 2027)


class TestStatus(unittest.TestCase):
    def setUp(self):
        self.sales = (
            seasonal.make_sale("Spring", (2027, 3, 18), (2027, 3, 25)),
            seasonal.make_sale("Winter", (2026, 12, 17), (2027, 1, 4)),
            seasonal.make_sale("Summer", (2027, 6, 24), (2027, 7, 8)),
        )

    def status(self, now):
        return seasonal.get_status(now, self.sales)

    def test_next_sale_is_the_soonest_one_not_the_first_listed(self):
        status = self.status(at(2026, 11, 1))
        self.assertIsNone(status.running)
        self.assertEqual([s.name for s in status.upcoming], ["Winter", "Spring", "Summer"])

    def test_a_running_sale_is_found(self):
        status = self.status(at(2026, 12, 25))
        self.assertEqual(status.running.name, "Winter")
        self.assertEqual([s.name for s in status.upcoming], ["Spring", "Summer"])

    def test_sale_starts_exactly_on_time(self):
        start = self.sales[1].start
        self.assertEqual(self.status(start).running.name, "Winter")
        self.assertIsNone(self.status(start - datetime.timedelta(seconds=1)).running)

    def test_sale_is_over_exactly_at_its_end_time(self):
        end = self.sales[1].end
        self.assertIsNone(self.status(end).running)
        self.assertEqual(self.status(end - datetime.timedelta(seconds=1)).running.name, "Winter")

    def test_nothing_upcoming_after_the_last_sale(self):
        status = self.status(at(2027, 8, 1))
        self.assertIsNone(status.running)
        self.assertEqual(status.upcoming, ())

    def test_uses_the_real_clock_when_no_time_is_given(self):
        status = seasonal.get_status()
        self.assertIsInstance(status.upcoming, tuple)


class TestTimeLeft(unittest.TestCase):
    def left(self, **kwargs):
        return seasonal.time_left(datetime.timedelta(**kwargs))

    def test_days_and_hours(self):
        self.assertEqual(self.left(days=46, hours=3, minutes=20), "46 days, 3 hours")

    def test_whole_days(self):
        self.assertEqual(self.left(days=2), "2 days")

    def test_one_day_is_not_plural(self):
        self.assertEqual(self.left(days=1, hours=1), "1 day, 1 hour")

    def test_hours_and_minutes(self):
        self.assertEqual(self.left(hours=5, minutes=12), "5 hours, 12 minutes")

    def test_minutes_only(self):
        self.assertEqual(self.left(minutes=7), "7 minutes")

    def test_under_a_minute(self):
        self.assertEqual(self.left(seconds=30), "less than a minute")


class TestEmbed(unittest.TestCase):
    def setUp(self):
        self.sales = (
            seasonal.make_sale("Winter Sale 2026", (2026, 12, 17), (2027, 1, 4)),
            seasonal.make_sale("Spring Sale 2027", (2027, 3, 18), (2027, 3, 25)),
            seasonal.make_sale("Summer Sale 2027", (2027, 6, 24), (2027, 7, 8)),
        )

    def test_before_a_sale_shows_the_next_one_with_time_left(self):
        embed = seasonal.build_embed(at(2026, 11, 1), self.sales)
        self.assertEqual(embed.title, "Next Steam sale: Winter Sale 2026")
        # Nov 1, 00:00 UTC to Dec 17, 18:00 UTC (10 AM Pacific)
        self.assertIn("Starts in **46 days, 18 hours**", embed.description)
        self.assertIn("<t:", embed.description)

    def test_later_sales_are_listed_after_the_next_one(self):
        embed = seasonal.build_embed(at(2026, 11, 1), self.sales)
        self.assertEqual(embed.fields[0].name, "After that")
        self.assertIn("Spring Sale 2027", embed.fields[0].value)
        self.assertIn("Summer Sale 2027", embed.fields[0].value)
        self.assertNotIn("Winter", embed.fields[0].value)

    def test_during_a_sale_shows_when_it_ends(self):
        embed = seasonal.build_embed(at(2026, 12, 25), self.sales)
        self.assertEqual(embed.title, "Winter Sale 2026 is on now!")
        self.assertIn("Ends in", embed.description)
        self.assertEqual(embed.fields[0].name, "Coming up")
        self.assertIn("Spring Sale 2027", embed.fields[0].value)

    def test_last_sale_has_no_extra_section(self):
        embed = seasonal.build_embed(at(2027, 5, 1), self.sales)
        self.assertEqual(embed.title, "Next Steam sale: Summer Sale 2027")
        self.assertEqual(len(embed.fields), 0)

    def test_empty_calendar_says_so_instead_of_a_wrong_countdown(self):
        embed = seasonal.build_embed(at(2027, 8, 1), self.sales)
        self.assertEqual(embed.description, seasonal.NO_UPCOMING)
        self.assertEqual(len(embed.fields), 0)

    def test_footer_mentions_the_start_time(self):
        embed = seasonal.build_embed(at(2026, 11, 1), self.sales)
        self.assertIn("10 AM Pacific", embed.footer.text)


class TestStoreCalendars(unittest.TestCase):
    def test_epic_and_gog_each_have_sales_listed(self):
        self.assertTrue(seasonal.EPIC_SALES)
        self.assertTrue(seasonal.GOG_SALES)
        for sale in seasonal.EPIC_SALES:
            self.assertEqual(sale.store, "Epic Games Store")
        for sale in seasonal.GOG_SALES:
            self.assertEqual(sale.store, "GOG")

    def test_every_store_sale_ends_after_it_starts(self):
        for sale in seasonal.EPIC_SALES + seasonal.GOG_SALES:
            self.assertLess(sale.start, sale.end, sale.name)

    def test_sales_of_one_store_do_not_overlap(self):
        for sales in (seasonal.SALES, seasonal.EPIC_SALES, seasonal.GOG_SALES):
            ordered = sorted(sales, key=lambda sale: sale.start)
            for earlier, later in zip(ordered, ordered[1:]):
                self.assertLessEqual(earlier.end, later.start, earlier.name)

    def test_all_sales_holds_every_store(self):
        self.assertEqual(seasonal.ALL_SALES, seasonal.SALES + seasonal.EPIC_SALES + seasonal.GOG_SALES)

    def test_steam_sales_are_not_marked_as_estimates(self):
        self.assertFalse(any(sale.estimated for sale in seasonal.SALES))

    def test_epic_sales_start_at_11_am_eastern(self):
        holiday = next(s for s in seasonal.EPIC_SALES if s.name == "Holiday Sale 2026")
        self.assertEqual(holiday.start.astimezone(UTC), at(2026, 12, 17, 16))
        summer = seasonal.make_sale("Summer", (2027, 7, 1), (2027, 7, 8), "Epic Games Store")
        self.assertEqual(summer.start.astimezone(UTC), at(2027, 7, 1, 15))  # daylight saving

    def test_gog_sales_start_at_2_pm_utc(self):
        winter = next(s for s in seasonal.GOG_SALES if s.name == "Winter Sale 2026")
        self.assertEqual(winter.start.astimezone(UTC), at(2026, 12, 14, 14))

    def test_a_sale_is_a_steam_sale_unless_said_otherwise(self):
        sale = seasonal.make_sale("Test", (2026, 1, 1), (2026, 1, 2))
        self.assertEqual(sale.store, "Steam")
        self.assertFalse(sale.estimated)

    def test_unknown_store_is_refused(self):
        with self.assertRaises(KeyError):
            seasonal.make_sale("Test", (2026, 1, 1), (2026, 1, 2), "Nowhere Store")


class TestStoreEmbed(unittest.TestCase):
    def setUp(self):
        self.sales = (
            seasonal.make_sale("Winter Sale 2026", (2026, 12, 17), (2027, 1, 4)),
            seasonal.make_sale("Epic Black Friday", (2026, 11, 19), (2026, 12, 1), "Epic Games Store", estimated=True),
            seasonal.make_sale("Epic Holiday", (2026, 12, 17), (2027, 1, 7), "Epic Games Store", estimated=True),
            seasonal.make_sale("GOG Black Friday", (2026, 11, 25), (2026, 12, 3), "GOG", estimated=True),
            seasonal.make_sale("GOG Confirmed", (2027, 2, 1), (2027, 2, 8), "GOG"),
        )

    def fields(self, now):
        embed = seasonal.build_embed(now, self.sales)
        return {field.name: field.value for field in embed.fields}

    def test_each_store_shows_its_own_next_sale(self):
        fields = self.fields(at(2026, 11, 15))
        self.assertIn("Epic Black Friday", fields["Epic Games Store"])
        self.assertIn("GOG Black Friday", fields["GOG"])
        self.assertNotIn("Epic Holiday", fields["Epic Games Store"])

    def test_time_left_is_counted_from_each_stores_start_time(self):
        fields = self.fields(at(2026, 11, 15))
        # Nov 19, 11 AM Eastern is 16:00 UTC; GOG Nov 25 is 14:00 UTC
        self.assertIn("starts in 4 days, 16 hours", fields["Epic Games Store"])
        self.assertIn("starts in 10 days, 14 hours", fields["GOG"])
        self.assertIn("<t:", fields["GOG"])

    def test_estimated_dates_are_labelled(self):
        fields = self.fields(at(2026, 11, 15))
        self.assertIn("(estimated)", fields["Epic Games Store"])
        self.assertIn("(estimated)", fields["GOG"])

    def test_confirmed_dates_are_not_labelled_as_estimates(self):
        fields = self.fields(at(2026, 12, 10))
        self.assertIn("GOG Confirmed", fields["GOG"])
        self.assertNotIn("(estimated)", fields["GOG"])

    def test_a_running_sale_shows_when_it_ends_and_what_is_next(self):
        fields = self.fields(at(2026, 11, 22))
        self.assertIn("**Epic Black Friday** is on now! Ends in", fields["Epic Games Store"])
        self.assertIn("Next: **Epic Holiday**", fields["Epic Games Store"])

    def test_a_store_with_no_upcoming_sale_says_so(self):
        fields = self.fields(at(2027, 3, 1))
        self.assertEqual(fields["Epic Games Store"], seasonal.NO_UPCOMING_STORE)
        self.assertEqual(fields["GOG"], seasonal.NO_UPCOMING_STORE)

    def test_steam_stays_the_headline(self):
        embed = seasonal.build_embed(at(2026, 11, 15), self.sales)
        self.assertEqual(embed.title, "Next Steam sale: Winter Sale 2026")
        self.assertEqual([field.name for field in embed.fields], ["Epic Games Store", "GOG"])

    def test_a_store_without_sales_is_left_out(self):
        steam_and_gog = tuple(sale for sale in self.sales if sale.store != "Epic Games Store")
        names = [field.name for field in seasonal.build_embed(at(2026, 11, 15), steam_and_gog).fields]
        self.assertEqual(names, ["GOG"])

    def test_footer_gives_each_stores_start_time(self):
        footer = seasonal.build_embed(at(2026, 11, 15), self.sales).footer.text
        self.assertIn("10 AM Pacific", footer)
        self.assertIn("11 AM Eastern", footer)
        self.assertIn("2 PM UTC", footer)

    def test_steam_only_embed_is_unchanged(self):
        embed = seasonal.build_embed(at(2026, 11, 15), self.sales[:1])
        self.assertEqual(len(embed.fields), 0)  # one Steam sale and no other stores, so no extra sections
        self.assertEqual(embed.footer.text, "Sales start at 10 AM Pacific Time • Dates can change")


class TestCommand(unittest.IsolatedAsyncioTestCase):
    def interaction(self):
        interaction = MagicMock()
        interaction.response.send_message = AsyncMock()
        return interaction

    async def test_replies_privately_with_an_embed(self):
        interaction = self.interaction()
        await bot.seasonal_command.callback(interaction)
        interaction.response.send_message.assert_awaited_once()
        kwargs = interaction.response.send_message.await_args.kwargs
        self.assertTrue(kwargs["ephemeral"])
        self.assertIn("10 AM Pacific", kwargs["embed"].footer.text)

    async def test_shows_the_next_sale_for_every_store(self):
        interaction = self.interaction()
        await bot.seasonal_command.callback(interaction)
        embed = interaction.response.send_message.await_args.kwargs["embed"]
        names = [field.name for field in embed.fields]
        self.assertIn("Epic Games Store", names)
        self.assertIn("GOG", names)

    async def test_works_in_direct_messages_too(self):
        self.assertFalse(bot.seasonal_command.guild_only)

    def test_command_is_registered(self):
        command = bot.bot.tree.get_command("seasonal")
        self.assertIs(command, bot.seasonal_command)


if __name__ == "__main__":
    unittest.main()