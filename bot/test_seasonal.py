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

    async def test_works_in_direct_messages_too(self):
        self.assertFalse(bot.seasonal_command.guild_only)

    def test_command_is_registered(self):
        command = bot.bot.tree.get_command("seasonal")
        self.assertIs(command, bot.seasonal_command)


if __name__ == "__main__":
    unittest.main()