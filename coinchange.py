# PRACTICAL EXAMPLE FOR PYTHON DEVELOPER JOBS.
# CODE A CASH REGISTER. WE WANT TO PRINT() THE NUMBER OF COINS THAT THE CASHIER HAVE TO GIVE AS A CHANGE TO THE CUSTOMER.
# DO THE EXAMPLE SUPPOSING THE CHANGE THAT THE CASHIER HAVE TO GIVE TO THE CUSTOMER IS 0.99

# THE LOGIC PROCESS IS EXPLAINED UNCOMMENTING THE PRINT FUNCTIONS IN THE CODE




def coin_change(coins):
    coins_to_give = coins
    coins_given = 0
    n_coins_given = 0
    type_of_coins = [0.50, 0.25, 0.10, 0.05, 0.01]
    tocp = 0
    while coins_given != coins:
        #print("coins_given is at " + str(coins_given) + " and coins is at " + str(coins))
        if coins_to_give >= float(type_of_coins[tocp]):
            coins_given += float(type_of_coins[tocp])
            n_coins_given += 1
            coins_to_give -= float(type_of_coins[tocp])
            #print("I gave one " + str(type_of_coins[tocp]))
            #print("I still owe the customer " + str(coins_to_give))
        else:
            if coins_to_give != round(coins_to_give, 2):
                #print("I dont know why i am supposed to give " + str(coins_to_give) + " to the customer, but i will solve my problem rounding it to " +  str(round(coins_to_give, 2)))
                coins_to_give = round(coins_to_give, 2)
                
            else:
                tocp += 1
                #print("tocp at " + str(tocp))
    return n_coins_given

print(coin_change(0.99))
