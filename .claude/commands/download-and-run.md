Run
uv run stock-data --config config/stock-data-1h.toml update-all

then run
uv run stock-data --config config/stock-data-1d.toml update-all

then
/stock-screening skill to create the screen all the stocks on hourly timeframe.
But do use daily and half hourly if required for more context of the stock data to zoom in or zoom out.
If required stock data is not present then download it using the @COMMANDS.md for sepcific symbol and timeframe.

Once done git commit the output report and push.