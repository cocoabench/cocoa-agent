**Task:**

You are given an online game to play at:
https://inbox-game.vercel.app/

In this game, incoming requests appear in an inbox and must be handled quickly and accurately. You fail if more than five requests are handled incorrectly or are not processed before their deadline.

Your objective is to survive the game until it ends while tracking the total number of requests sent by each individual throughout the game. If you fail, the totals you recorded will be incomplete or incorrect. Therefore, if you fail at any point, you should restart the game and repeat the process until you successfully survive and process all requests.

After the game ends without you failing: (1) Identify the person who sent the highest number of requests. (2) Extract only that person’s last name. (3) Count the total number of requests sent by that person.

**Output Format:**

Output only one answer, and format the answer as:

<answer>LastName,Count</answer>

Do not include spaces before or after the comma.

**Example:**

```
<answer>Zhang,15</answer>
```

Submit your answer using the same format as the example above.
