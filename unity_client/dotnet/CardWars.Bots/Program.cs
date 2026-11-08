// Pruebas de extremo a extremo del cliente C# (el mismo código que usa Unity)
// contra el servidor Python real.
//
//   .venv/bin/python backend/app.py                      # terminal 1 (desde card_ar_poc/)
//   dotnet run --project unity_client/dotnet/CardWars.Bots -- ws://localhost:5001/ws
//
// Cada escenario usa una sala propia (game_id único): no molesta a jugadores reales.
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Linq;
using System.Threading;
using CardWars.Core;

internal static class Program
{
    private static Uri _server;
    private static int _failures;

    private static int Main(string[] args)
    {
        _server = new Uri(args.Length > 0 ? args[0] : "ws://localhost:5001/ws");
        Console.WriteLine($"Servidor: {_server}\n");

        Run("Partida completa entre dos bots", FullGame);
        Run("10 partidas aleatorias terminan y ambos clientes coinciden", ManyGames);
        Run("Errores del servidor llegan con su código", ServerErrors);
        Run("Acción duplicada no se aplica dos veces", DuplicateAction);
        Run("Reconexión con token conserva el puesto", Reconnect);
        Run("Revancha", Rematch);

        Console.WriteLine(_failures == 0 ? "\nTODO OK" : $"\n{_failures} escenario(s) FALLARON");
        return _failures == 0 ? 0 : 1;
    }

    // ------------------------------------------------------------------ escenarios
    private static void FullGame()
    {
        var (a, b, room) = Pair();
        var log = new List<string>();
        GameState prev = null;
        b.StateChanged += (s, events) =>
        {
            foreach (var ev in events)
            {
                var line = EventDescriber.Describe(ev, prev, s);
                if (line != null) log.Add(line);
            }
            prev = s;
        };
        PlayToEnd(a, b, new Random(1));
        foreach (var line in log) Console.WriteLine("    " + line);
        AssertConsistent(a, b);
        Check(a.State.WinnerId != null, "debe haber ganador");
        Dispose(a, b);
    }

    private static void ManyGames()
    {
        var rng = new Random(42);
        for (var i = 0; i < 10; i++)
        {
            var (a, b, _) = Pair();
            var turns = PlayToEnd(a, b, rng);
            AssertConsistent(a, b);
            var winner = a.State.Players.First(p => p.PlayerId == a.State.WinnerId).Name;
            Console.WriteLine($"    partida {i + 1}: {turns} acciones, gana {winner}, seq={a.LastSeq}");
            Dispose(a, b);
        }
    }

    private static void ServerErrors()
    {
        var (a, b, _) = Pair();
        var errors = new List<string>();
        b.ErrorReceived += (e, actionId) => errors.Add(e.Code);
        // B intenta jugar fuera de turno saltándose la validación local.
        b.SendRawAsync(MessageType.PlayCard, new PlayCardPayload { CardId = "mage", ExpectedTurn = 1 }, "x1").Wait();
        Check(WaitUntil(() => errors.Count > 0, 3000, a, b), "esperaba un error");
        Check(errors[0] == ErrorCode.NotYourTurn, $"código esperado not_your_turn, llegó {errors[0]}");
        // La validación local también lo impide sin ir a la red:
        Check(!b.PlayCardAsync("mage").Result, "PlayCardAsync debería rechazarlo localmente");
        Dispose(a, b);
    }

    private static void DuplicateAction()
    {
        var (a, b, _) = Pair();
        var payload = new PlayCardPayload { CardId = "mage", ExpectedTurn = 1, Source = "ui" };
        a.SendRawAsync(MessageType.PlayCard, payload, "dup-1").Wait();
        Check(WaitUntil(() => b.State.TurnNumber == 2, 3000, a, b), "la jugada no llegó");
        var life = b.Me.Life;
        a.SendRawAsync(MessageType.PlayCard, payload, "dup-1").Wait();   // reintento idéntico
        WaitUntil(() => false, 500, a, b);
        Check(b.Me.Life == life && b.Me.Life == 60, $"vida de B debería seguir en 60, es {b.Me.Life}");
        Dispose(a, b);
    }

    private static void Reconnect()
    {
        var room = "bots-" + Guid.NewGuid().ToString("N").Substring(0, 8);
        var storeA = new InMemorySessionStore();
        var a = Connect("A", room, storeA);
        var b = Connect("B", room, new InMemorySessionStore());
        Check(WaitUntil(() => a.State?.Status == GameStatus.InProgress, 3000, a, b), "no empezó");
        var originalId = a.PlayerId;
        a.Dispose();                                     // se cae la conexión de A
        Check(WaitUntil(() => b.Rival != null && !b.Rival.Connected, 3000, b), "B no vio la desconexión");

        var a2 = Connect("A", room, storeA);             // mismo almacén = mismo token
        Check(WaitUntil(() => a2.State != null, 3000, a2, b), "A no recibió estado");
        Check(a2.PlayerId == originalId, "A debería recuperar su puesto");
        Check(WaitUntil(() => b.Rival.Connected, 3000, a2, b), "B no vio la reconexión");
        Check(a2.State.Status == GameStatus.InProgress, "la partida debería seguir en curso");
        Dispose(a2, b);
    }

    private static void Rematch()
    {
        var (a, b, _) = Pair();
        PlayToEnd(a, b, new Random(7));
        a.RematchAsync().Wait();
        b.RematchAsync().Wait();
        Check(WaitUntil(() => a.State.Status == GameStatus.InProgress && b.State.Status == GameStatus.InProgress,
                        3000, a, b), "la revancha no empezó");
        Check(a.Me.Life == 100 && a.Me.Hand.Count == 3, "estado inicial incorrecto tras la revancha");
        Dispose(a, b);
    }

    // ------------------------------------------------------------------ helpers
    private static (GameClient, GameClient, string) Pair()
    {
        var room = "bots-" + Guid.NewGuid().ToString("N").Substring(0, 8);
        var a = Connect("BotA", room, new InMemorySessionStore());
        var b = Connect("BotB", room, new InMemorySessionStore());
        Check(WaitUntil(() => a.State?.Status == GameStatus.InProgress && b.State?.Status == GameStatus.InProgress,
                        3000, a, b), "la partida no empezó");
        return (a, b, room);
    }

    private static GameClient Connect(string name, string room, ISessionStore store)
    {
        var client = new GameClient(new WebSocketTransport(), store);
        var welcomed = false;
        client.Welcomed += _ => welcomed = true;
        client.ConnectAsync(_server, name, room).Wait();
        Check(WaitUntil(() => welcomed, 3000, client), $"{name}: sin welcome");
        return client;
    }

    /// <summary>Ambos bots juegan: atacar si hay criatura; si no, carta al azar.</summary>
    private static int PlayToEnd(GameClient a, GameClient b, Random rng)
    {
        var actions = 0;
        var sw = Stopwatch.StartNew();
        while (sw.ElapsedMilliseconds < 15000)
        {
            a.Poll();
            b.Poll();
            if (a.State.Status == GameStatus.Finished && b.State.Status == GameStatus.Finished
                && a.LastSeq == b.LastSeq)
            {
                return actions;
            }
            foreach (var c in new[] { a, b })
            {
                if (c.CanAttack)
                {
                    c.AttackAsync().Wait();
                    actions++;
                }
                else if (c.CanPlayCard)
                {
                    c.PlayCardAsync(c.Me.Hand[rng.Next(c.Me.Hand.Count)]).Wait();
                    actions++;
                }
            }
            Thread.Sleep(5);
        }
        throw new Exception("la partida no terminó en 15 s");
    }

    private static void AssertConsistent(GameClient a, GameClient b)
    {
        Check(a.LastSeq == b.LastSeq, $"seq distinto: {a.LastSeq} vs {b.LastSeq}");
        Check(a.State.WinnerId == b.State.WinnerId, "ganador distinto");
        foreach (var pa in a.State.Players)
        {
            var pb = b.State.Players.First(p => p.PlayerId == pa.PlayerId);
            Check(pa.Life == pb.Life, $"vida distinta para {pa.Name}");
        }
        // Información oculta: veo mi mano, no la del rival.
        Check(a.Me.Hand != null && a.Rival.Hand == null, "información oculta rota");
    }

    private static bool WaitUntil(Func<bool> condition, int timeoutMs, params GameClient[] clients)
    {
        var sw = Stopwatch.StartNew();
        while (sw.ElapsedMilliseconds < timeoutMs)
        {
            foreach (var c in clients) c.Poll();
            if (condition()) return true;
            Thread.Sleep(10);
        }
        return false;
    }

    private static void Check(bool condition, string message)
    {
        if (!condition) throw new Exception(message);
    }

    private static void Dispose(params GameClient[] clients)
    {
        foreach (var c in clients) c.Dispose();
    }

    private static void Run(string name, Action scenario)
    {
        Console.WriteLine($"- {name}");
        try
        {
            scenario();
            Console.WriteLine("  OK");
        }
        catch (Exception e)
        {
            _failures++;
            var inner = e is AggregateException ae ? ae.InnerException : e;
            Console.WriteLine($"  FALLO: {inner?.Message}");
        }
    }
}
