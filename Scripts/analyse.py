"""
Application entry point for the flight analysis toolkit.

All execution paths (CLI, regression, future GUI) originate here.
"""


def cruise_analysis():
    print("\nCruise Analysis")
    print("Not implemented.")


def autotune_review():
    from analyses.autotune import AutotuneAnalysisPresentation

    AutotuneAnalysisPresentation().run()


def sensor_diagnostics():
    print("\nSensor Diagnostics")
    print("Not implemented.")


def log_summary():
    print("\nLog Summary")
    print("Not implemented.")


def menu():

    while True:

        print("\nFlight Analysis")
        print("================")
        print("1. Landing Analysis")
        print("2. Event Timeline")
        print("3. Battery Analysis")
        print("4. Cruise Analysis")
        print("5. Autotune Review")
        print("6. Sensor Diagnostics")
        print("7. Log Summary")
        print("8. Battery Pack Management")
        print("9. Pack Performance Report")
        print("10. Takeoff Analysis")
        print("11. Radio Link Analysis")
        print("12. Radio Link Range-Walk Comparison")
        print("13. Stall Analysis")

        print("0. Exit")

        choice = input("\nSelection: ").strip()

        if choice == "1":
            from analyses.landing import LandingAnalysis

            landing = LandingAnalysis()
            landing.run()

        elif choice == "2":
            from analyses.event_timeline import EventTimelineAnalysis

            analysis = EventTimelineAnalysis()
            analysis.run()

        elif choice == "3":
            from analyses.battery import BatteryAnalysisPresentation
            analysis = BatteryAnalysisPresentation()
            analysis.run()

        elif choice == "4":
            cruise_analysis()

        elif choice == "5":
            autotune_review()

        elif choice == "6":
            sensor_diagnostics()

        elif choice == "7":
            log_summary()

        elif choice == "8":

            from analyses.battery import BatteryPackManagementPresentation

            analysis = BatteryPackManagementPresentation()

            analysis.run()

        elif choice == "9":

            from analyses.battery import BatteryPackPerformancePresentation

            analysis = BatteryPackPerformancePresentation()

            analysis.run()

        elif choice == "10":

            from analyses.takeoff import TakeoffAnalysisPresentation

            analysis = TakeoffAnalysisPresentation()

            analysis.run()

        elif choice == "11":

            from analyses.radio_link import RadioLinkAnalysisPresentation

            RadioLinkAnalysisPresentation().run()

        elif choice == "12":

            from analyses.range_walk import RangeWalkComparisonPresentation

            RangeWalkComparisonPresentation().run()

        elif choice == "13":

            from analyses.stall import StallAnalysisPresentation

            StallAnalysisPresentation().run()

        elif choice == "0":
            break

        else:
            print("Invalid selection.")


if __name__ == "__main__":
    menu()
